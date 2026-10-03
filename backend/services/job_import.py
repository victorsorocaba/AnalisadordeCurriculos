"""Import public job metadata from a restricted set of job sites."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


class ImportRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2000)


TRUSTED_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co",
                 "remotive.com", "himalayas.app", "www.linkedin.com", "br.linkedin.com",
                 "br.indeed.com", "www.indeed.com.br", "www.glassdoor.com.br"}


class JobHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.json_blocks: list[str] = []
        self._script = False
        self._title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key and attrs.get("content"):
                self.meta[key.lower()] = attrs["content"]
        elif tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._script = True
            self.json_blocks.append("")
        elif tag == "title":
            self._title = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False
        elif tag == "title":
            self._title = False

    def handle_data(self, data):
        if self._script and self.json_blocks:
            self.json_blocks[-1] += data
        if self._title:
            self.title += data


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _jobposting(value):
    if isinstance(value, list):
        for item in value:
            result = _jobposting(item)
            if result:
                return result
    if isinstance(value, dict):
        kind = value.get("@type", "")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return value
        return _jobposting(value.get("@graph", []))
    return None


def parse_job_html(body: str, url: str) -> dict:
    parser = JobHTML()
    parser.feed(body)
    posting = None
    for block in parser.json_blocks:
        try:
            posting = _jobposting(json.loads(block))
            if posting:
                break
        except ValueError:
            continue
    posting = posting or {}
    org = posting.get("hiringOrganization") or {}
    company = org.get("name", "") if isinstance(org, dict) else ""
    host = urlparse(url).hostname or ""
    source = ("Gupy" if host.endswith(".gupy.io") else "LinkedIn" if "linkedin.com" in host
              else "Indeed" if "indeed.com" in host else "Glassdoor" if "glassdoor.com" in host
              else "Greenhouse" if "greenhouse.io" in host else "Lever" if host == "jobs.lever.co"
              else "Remotive" if host == "remotive.com" else "Himalayas" if host == "himalayas.app" else host)
    return {
        "role": _plain(str(posting.get("title") or parser.meta.get("og:title") or parser.title))[:160],
        "company": _plain(str(company))[:160],
        "source": source[:120],
        "vacancyUrl": url,
        "jobDescription": _plain(str(posting.get("description") or parser.meta.get("description") or parser.meta.get("og:description") or ""))[:20_000],
    }


async def import_job(url: str) -> dict:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Link da vaga inválido.") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise HTTPException(422, "Use um link HTTPS público de uma plataforma de vagas.")
    if host not in TRUSTED_HOSTS and not host.endswith(".gupy.io"):
        raise HTTPException(422, "Importação automática disponível para Gupy, LinkedIn, Indeed, Glassdoor, Greenhouse, Lever, Remotive e Himalayas. Cole a descrição manualmente para outros sites.")
    try:
        addresses = await run_in_threadpool(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise HTTPException(422, "O endereço da vaga não é público.")
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url, headers={"User-Agent": "Alinha/1.0 (public job metadata)", "Accept": "text/html"}) as response:
                if response.status_code != 200:
                    raise HTTPException(422, "A plataforma não permitiu ler a vaga. Cole os dados manualmente.")
                if "text/html" not in response.headers.get("content-type", ""):
                    raise HTTPException(422, "O link não retornou uma página de vaga.")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        raise HTTPException(422, "A página da vaga é grande demais para importar.")
                    chunks.append(chunk)
                body = b"".join(chunks).decode("utf-8", errors="replace")
    except HTTPException:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise HTTPException(422, "Não foi possível acessar a vaga. Cole os dados manualmente.") from exc
    data = parse_job_html(body, url)
    if not data["role"] and not data["jobDescription"]:
        raise HTTPException(422, "Esta página não expõe os dados da vaga. Cole-os manualmente.")
    return data
