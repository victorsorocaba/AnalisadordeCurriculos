"""PostgreSQL persistence for saved resume versions and roadmap progress."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.models.detailed import DetailedAnalysis

router = APIRouter(prefix="/api/storage", tags=["storage"])
PROFILE_KEY = re.compile(r"^[A-Za-z0-9_-]{43}$")
ROADMAP_ID = re.compile(r"^[a-z0-9-]{1,100}$")
STATUSES = {"saved", "studying", "completed"}


@lru_cache(maxsize=1)
def _valid_topics() -> dict[str, set[str]]:
    path = Path(__file__).resolve().parent.parent / "frontend" / "study-topics.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))["roadmaps"]
    return {
        slug: {topic["id"] for section in data["sections"] for topic in section["topics"]}
        for slug, data in catalog.items()
    }


def _check_topic(roadmap_id: str, topic_id: str) -> None:
    if topic_id not in _valid_topics().get(roadmap_id, set()):
        raise HTTPException(404, "Assunto não encontrado nesta rota.")


class SavedVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    date: datetime
    label: str = Field(min_length=1, max_length=100)
    jobDescription: str = Field(default="", max_length=20_000)
    percentage: int = Field(ge=0, le=100)
    analysis: DetailedAnalysis


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    if os.getenv("PGHOST"):
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            host=os.environ["PGHOST"], port=os.getenv("PGPORT", "5432"),
            dbname=os.getenv("PGDATABASE", "alinha"), user=os.getenv("PGUSER", "alinha"),
            password=os.getenv("PGPASSWORD", ""),
        )
    return ""


def _owner(x_profile_key: str | None = Header(default=None)) -> str:
    if not x_profile_key or not PROFILE_KEY.fullmatch(x_profile_key):
        raise HTTPException(401, "Chave do perfil ausente ou inválida.")
    return hashlib.sha256(x_profile_key.encode("ascii")).hexdigest()


def _connect():
    if not _database_url():
        raise HTTPException(503, "O armazenamento PostgreSQL não está configurado.")
    import psycopg

    try:
        return psycopg.connect(_database_url(), connect_timeout=5)
    except psycopg.OperationalError as exc:
        raise HTTPException(503, "O banco de dados está indisponível.") from exc


@router.get("/status")
def storage_status() -> dict[str, bool]:
    return {"enabled": bool(_database_url())}


@router.get("/health", include_in_schema=False)
def storage_health() -> dict[str, str]:
    with _connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/versions")
def list_versions(x_profile_key: str | None = Header(default=None)) -> list[dict]:
    owner = _owner(x_profile_key)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, label, job_description, percentage, analysis "
            "FROM saved_versions WHERE owner_hash = %s "
            "ORDER BY created_at DESC, id DESC LIMIT 10", (owner,),
        ).fetchall()
    return [
        {"id": str(row[0]), "date": row[1].isoformat(), "label": row[2],
         "jobDescription": row[3], "percentage": row[4], "analysis": row[5]}
        for row in rows
    ]


@router.post("/versions", status_code=201)
def save_version(version: SavedVersion, x_profile_key: str | None = Header(default=None)) -> dict[str, str]:
    from psycopg.types.json import Jsonb

    owner = _owner(x_profile_key)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO saved_versions (id, owner_hash, created_at, label, job_description, percentage, analysis) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (version.id, owner, version.date, version.label, version.jobDescription,
             version.percentage, Jsonb(version.analysis.model_dump())),
        )
        conn.execute(
            "DELETE FROM saved_versions WHERE id IN ("
            "SELECT id FROM saved_versions WHERE owner_hash = %s "
            "ORDER BY created_at DESC, id DESC OFFSET 10)", (owner,),
        )
    return {"id": str(version.id)}


@router.delete("/versions/{version_id}", status_code=204)
def delete_version(version_id: UUID, x_profile_key: str | None = Header(default=None)) -> Response:
    owner = _owner(x_profile_key)
    with _connect() as conn:
        conn.execute("DELETE FROM saved_versions WHERE id = %s AND owner_hash = %s", (version_id, owner))
    return Response(status_code=204)


@router.get("/roadmaps")
def list_roadmaps(x_profile_key: str | None = Header(default=None)) -> dict[str, str]:
    owner = _owner(x_profile_key)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT roadmap_id, status FROM roadmap_progress WHERE owner_hash = %s", (owner,),
        ).fetchall()
    return dict(rows)


@router.put("/roadmaps")
def import_roadmaps(progress: dict[str, str], x_profile_key: str | None = Header(default=None)) -> dict[str, int]:
    owner = _owner(x_profile_key)
    if len(progress) > 200 or any(not ROADMAP_ID.fullmatch(key) or value not in STATUSES for key, value in progress.items()):
        raise HTTPException(422, "Planejamento de estudos inválido.")
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO roadmap_progress (owner_hash, roadmap_id, status) VALUES (%s, %s, %s) "
                "ON CONFLICT (owner_hash, roadmap_id) DO NOTHING",
                [(owner, key, value) for key, value in progress.items()],
            )
    return {"imported": len(progress)}


class RoadmapStatus(BaseModel):
    status: str


@router.put("/roadmaps/{roadmap_id}")
def set_roadmap(roadmap_id: str, body: RoadmapStatus, x_profile_key: str | None = Header(default=None)) -> dict[str, str]:
    owner = _owner(x_profile_key)
    if not ROADMAP_ID.fullmatch(roadmap_id) or body.status not in STATUSES:
        raise HTTPException(422, "Rota ou situação inválida.")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO roadmap_progress (owner_hash, roadmap_id, status) VALUES (%s, %s, %s) "
            "ON CONFLICT (owner_hash, roadmap_id) DO UPDATE SET status = EXCLUDED.status, updated_at = now()",
            (owner, roadmap_id, body.status),
        )
    return {"status": body.status}


@router.delete("/roadmaps/{roadmap_id}", status_code=204)
def delete_roadmap(roadmap_id: str, x_profile_key: str | None = Header(default=None)) -> Response:
    owner = _owner(x_profile_key)
    if not ROADMAP_ID.fullmatch(roadmap_id):
        raise HTTPException(422, "Rota inválida.")
    with _connect() as conn:
        conn.execute(
            "DELETE FROM roadmap_progress WHERE owner_hash = %s AND roadmap_id = %s", (owner, roadmap_id))
    return Response(status_code=204)


@router.get("/topics")
def list_topics(x_profile_key: str | None = Header(default=None)) -> dict[str, list[str]]:
    owner = _owner(x_profile_key)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT roadmap_id, topic_id FROM roadmap_topic_progress WHERE owner_hash = %s",
            (owner,),
        ).fetchall()
    progress: dict[str, list[str]] = {}
    for roadmap_id, topic_id in rows:
        progress.setdefault(roadmap_id, []).append(topic_id.strip())
    return progress


@router.put("/topics")
def import_topics(progress: dict[str, list[str]], x_profile_key: str | None = Header(default=None)) -> dict[str, int]:
    owner = _owner(x_profile_key)
    if len(progress) > 200 or sum(map(len, progress.values())) > 2000:
        raise HTTPException(422, "Progresso de estudos inválido.")
    entries = []
    for roadmap_id, topic_ids in progress.items():
        if not isinstance(topic_ids, list):
            raise HTTPException(422, "Progresso de estudos inválido.")
        for topic_id in set(topic_ids):
            _check_topic(roadmap_id, topic_id)
            entries.append((owner, roadmap_id, topic_id))
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO roadmap_topic_progress (owner_hash, roadmap_id, topic_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (owner_hash, roadmap_id, topic_id) DO NOTHING",
                entries,
            )
    return {"imported": len(entries)}


@router.put("/topics/{roadmap_id}/{topic_id}")
def complete_topic(roadmap_id: str, topic_id: str, x_profile_key: str | None = Header(default=None)) -> dict[str, bool]:
    owner = _owner(x_profile_key)
    _check_topic(roadmap_id, topic_id)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO roadmap_topic_progress (owner_hash, roadmap_id, topic_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (owner_hash, roadmap_id, topic_id) DO NOTHING",
            (owner, roadmap_id, topic_id),
        )
    return {"completed": True}


@router.delete("/topics/{roadmap_id}/{topic_id}", status_code=204)
def uncomplete_topic(roadmap_id: str, topic_id: str, x_profile_key: str | None = Header(default=None)) -> Response:
    owner = _owner(x_profile_key)
    _check_topic(roadmap_id, topic_id)
    with _connect() as conn:
        conn.execute(
            "DELETE FROM roadmap_topic_progress WHERE owner_hash = %s AND roadmap_id = %s AND topic_id = %s",
            (owner, roadmap_id, topic_id),
        )
    return Response(status_code=204)
