"""Search official job APIs and rank listings by evidence in the resume."""

import asyncio
import html
import os
import re
import time
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from backend.models.jobs import JobListing, JobSearchRequest, JobSearchResult


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain(value: object, limit: int = 360) -> str:
    parser = _TextParser()
    parser.feed(str(value or ""))
    text = html.unescape(" ".join(parser.parts))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _has_term(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(_norm(term)) + r"(?!\w)", text))


def _safe_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.netloc else ""


def _search_terms(request: JobSearchRequest) -> tuple[str, list[str]]:
    skills = []
    for line in request.draft.skills.splitlines():
        term = line.strip().lstrip("-• ")
        if 3 <= len(term) <= 35 and _norm(term) not in {_norm(item) for item in skills}:
            skills.append(term)
    query = request.query.strip()
    if not query:
        query = next((skill for skill in skills if len(skill.split()) <= 2), "")
    if not query:
        query = request.draft.headline.split("|")[0].strip()[:70]
    return query[:120], skills[:20]


def _remote_for_brazil(location: str) -> bool:
    value = _norm(location)
    return any(term in value for term in (
        "worldwide", "anywhere", "global", "brazil", "brasil", "latam",
        "latin america", "south america", "americas", "international",
    ))


_remotive_cache: tuple[float, list[dict]] = (0.0, [])
_remotive_lock = asyncio.Lock()


async def _remotive(client: httpx.AsyncClient) -> list[dict]:
    global _remotive_cache
    async with _remotive_lock:
        stamp, cached = _remotive_cache
        if cached and time.monotonic() - stamp < 6 * 3600:
            return cached
        response = await client.get("https://remotive.com/api/remote-jobs")
        response.raise_for_status()
        items = response.json().get("jobs", [])
        if not isinstance(items, list):
            raise ValueError("Invalid Remotive response")
        _remotive_cache = (time.monotonic(), items)
        return items


async def _himalayas(client: httpx.AsyncClient, query: str) -> list[dict]:
    response = await client.get(
        "https://himalayas.app/jobs/api/search",
        params={"q": query, "country": "BR", "sort": "relevant", "page": 1},
    )
    response.raise_for_status()
    return response.json().get("jobs", [])


async def _jooble(client: httpx.AsyncClient, query: str, location: str) -> list[dict]:
    key = os.getenv("JOOBLE_BR_API_KEY", "").strip()
    response = await client.post(
        f"https://br.jooble.org/api/{key}",
        json={"keywords": query, "location": location or "Brasil", "page": 1, "ResultOnPage": 20},
    )
    response.raise_for_status()
    return response.json().get("jobs", [])


async def _adzuna(client: httpx.AsyncClient, query: str, location: str) -> list[dict]:
    response = await client.get(
        "https://api.adzuna.com/v1/api/jobs/br/search/1",
        params={
            "app_id": os.getenv("ADZUNA_APP_ID", "").strip(),
            "app_key": os.getenv("ADZUNA_APP_KEY", "").strip(),
            "results_per_page": 20, "what": query, "where": location,
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json().get("results", [])


def _listing(source: str, item: dict) -> dict | None:
    if source == "Himalayas":
        data = {
            "title": item.get("title"), "company": item.get("companyName"),
            "location": ", ".join(item.get("locationRestrictions") or []) or "Remoto",
            "description": item.get("description") or item.get("excerpt"),
            "url": item.get("applicationLink"), "published_at": str(item.get("pubDate") or ""),
            "remote": True, "seniority": ", ".join(item.get("seniority") or []),
        }
    elif source == "Remotive":
        location = str(item.get("candidate_required_location") or "")
        if not _remote_for_brazil(location):
            return None
        data = {
            "title": item.get("title"), "company": item.get("company_name"),
            "location": location or "Remoto", "description": item.get("description"),
            "url": item.get("url"), "published_at": str(item.get("publication_date") or ""),
            "remote": True, "seniority": "",
        }
    elif source == "Jooble":
        data = {
            "title": item.get("title"), "company": item.get("company"),
            "location": item.get("location"), "description": item.get("snippet"),
            "url": item.get("link"), "published_at": str(item.get("updated") or ""),
            "remote": "remot" in _norm(str(item.get("title", "")) + " " + str(item.get("location", ""))),
            "seniority": "",
        }
    else:
        data = {
            "title": item.get("title"), "company": (item.get("company") or {}).get("display_name"),
            "location": (item.get("location") or {}).get("display_name"),
            "description": item.get("description"), "url": item.get("redirect_url"),
            "published_at": str(item.get("created") or ""),
            "remote": "remot" in _norm(str(item.get("title", "")) + " " + str(item.get("description", ""))),
            "seniority": "",
        }
    url = _safe_url(data["url"])
    title = _plain(data["title"], 150)
    if not url or not title:
        return None
    return {
        "source": source, "title": title, "company": _plain(data["company"], 100) or "Empresa não informada",
        "location": _plain(data["location"], 120) or "Local não informado",
        "description": _plain(data["description"], 360), "search_text": _norm(_plain(data["description"], 20000)),
        "url": url, "published_at": data["published_at"][:35], "remote": data["remote"],
        "seniority": _plain(data["seniority"], 80),
    }


def _score(item: dict, query: str, skills: list[str], entry_level: bool = False) -> JobListing | None:
    title = _norm(item["title"])
    text = title + " " + item["search_text"]
    matched = [term for term in skills if _has_term(text, term)]
    query_words = [word for word in re.findall(r"\w+", _norm(query)) if len(word) >= 3]
    title_match = bool(query_words and all(_has_term(title, word) for word in query_words))
    title_partial = bool(query_words and any(_has_term(title, word) for word in query_words))
    text_match = bool(query_words and all(_has_term(text, word) for word in query_words))
    entry_title = bool(re.search(r"\b(junior|jr|intern|internship|estagio|estagiario|trainee)\b", title))
    if entry_level and entry_title and text_match and matched:
        title_partial = True
    if not title_partial:
        return None
    score = min(95, 20 + min(len(matched), 5) * 12 + (25 if title_match else 10) + (10 if text_match else 0) + (15 if entry_level and entry_title else 0))
    return JobListing(
        source=item["source"], title=item["title"], company=item["company"],
        location=item["location"], remote=item["remote"], url=item["url"],
        description=item["description"], published_at=item["published_at"],
        match_score=score, matched_terms=matched[:6],
    )


def _entry_level_resume(request: JobSearchRequest) -> bool:
    text = _norm(request.draft.headline + " " + request.draft.summary)
    return bool(re.search(r"\b(estagi\w*|estudant\w*|junior|trainee|entry.level)\b", text))


def _senior_role(item: dict) -> bool:
    text = _norm(item["title"] + " " + item["seniority"])
    return bool(re.search(r"\b(senior|sr|lead|staff|principal|manager|director|pleno|mid.level|gerente|lider)\b", text))


async def search_jobs(request: JobSearchRequest) -> JobSearchResult:
    query, skills = _search_terms(request)
    entry_level = _entry_level_resume(request)
    if not query:
        return JobSearchResult(jobs=[], query_used="", sources=[], notices=["Informe um cargo ou habilidade para buscar vagas."])
    tasks = []
    sources = []
    notices = []
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        if request.work_mode != "local":
            searches = [f"junior {query}", f"estagio {query}"] if entry_level else [query]
            for search in searches:
                sources.append("Himalayas")
                tasks.append(_himalayas(client, search))
            sources.append("Remotive")
            tasks.append(_remotive(client))
        if request.work_mode != "remote":
            if os.getenv("JOOBLE_BR_API_KEY", "").strip():
                sources.append("Jooble")
                tasks.append(_jooble(client, query, request.location.strip()))
            if os.getenv("ADZUNA_APP_ID", "").strip() and os.getenv("ADZUNA_APP_KEY", "").strip():
                sources.append("Adzuna")
                tasks.append(_adzuna(client, query, request.location.strip()))
            if not os.getenv("JOOBLE_BR_API_KEY", "").strip() and not (os.getenv("ADZUNA_APP_ID", "").strip() and os.getenv("ADZUNA_APP_KEY", "").strip()):
                notices.append("Vagas locais exigem chaves das APIs Jooble Brasil ou Adzuna na configuração do servidor.")
        results = await asyncio.gather(*tasks, return_exceptions=True)
    jobs = []
    successful_sources = []
    for source, result in zip(sources, results):
        if isinstance(result, Exception) or not isinstance(result, list):
            notices.append(f"{source}: busca temporariamente indisponível.")
            continue
        successful_sources.append(source)
        for raw in result[:300]:
            if not isinstance(raw, dict):
                continue
            item = _listing(source, raw)
            if item and not (entry_level and _senior_role(item)) and (request.work_mode != "local" or not item["remote"]):
                ranked = _score(item, query, skills, entry_level=entry_level)
                if ranked:
                    jobs.append(ranked)
    unique = {}
    for job in jobs:
        key = (_norm(job.title), _norm(job.company))
        if key not in unique or job.match_score > unique[key].match_score:
            unique[key] = job
    ordered = sorted(unique.values(), key=lambda job: (job.match_score, job.published_at), reverse=True)[:24]
    return JobSearchResult(jobs=ordered, query_used=query, sources=list(dict.fromkeys(successful_sources)), notices=list(dict.fromkeys(notices)))
