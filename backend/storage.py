"""PostgreSQL persistence for resumes, study progress, and applications."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

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


class JobApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=120)
    vacancyUrl: HttpUrl | None = None
    appliedOn: date
    responseReceived: bool = False
    notes: str = Field(default="", max_length=1000)
    status: str = Field(default="applied", pattern="^(saved|applying|applied|interviewing|offer|accepted|rejected|withdrawn)$")
    followUpOn: date | None = None
    contactName: str = Field(default="", max_length=160)
    contactEmail: str = Field(default="", max_length=254)
    resumeVersionId: UUID | None = None
    jobDescription: str = Field(default="", max_length=20_000)
    coverLetter: str = Field(default="", max_length=10_000)
    recruiterMessage: str = Field(default="", max_length=3_000)
    interviewPrep: str = Field(default="", max_length=10_000)


class ImportedJobApplication(JobApplicationInput):
    id: UUID


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


def _owner(x_profile_key: str | None = Header(default=None),
           x_session_token: str | None = Header(default=None)) -> str:
    if x_session_token:
        from backend.accounts import session_owner
        return session_owner(x_session_token)
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
def list_versions(owner: str = Depends(_owner)) -> list[dict]:
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
def save_version(version: SavedVersion, owner: str = Depends(_owner)) -> dict[str, str]:
    from psycopg.types.json import Jsonb

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
def delete_version(version_id: UUID, owner: str = Depends(_owner)) -> Response:
    with _connect() as conn:
        conn.execute("DELETE FROM saved_versions WHERE id = %s AND owner_hash = %s", (version_id, owner))
    return Response(status_code=204)


@router.get("/roadmaps")
def list_roadmaps(owner: str = Depends(_owner)) -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT roadmap_id, status FROM roadmap_progress WHERE owner_hash = %s", (owner,),
        ).fetchall()
    return dict(rows)


@router.put("/roadmaps")
def import_roadmaps(progress: dict[str, str], owner: str = Depends(_owner)) -> dict[str, int]:
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
def set_roadmap(roadmap_id: str, body: RoadmapStatus, owner: str = Depends(_owner)) -> dict[str, str]:
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
def delete_roadmap(roadmap_id: str, owner: str = Depends(_owner)) -> Response:
    if not ROADMAP_ID.fullmatch(roadmap_id):
        raise HTTPException(422, "Rota inválida.")
    with _connect() as conn:
        conn.execute(
            "DELETE FROM roadmap_progress WHERE owner_hash = %s AND roadmap_id = %s", (owner, roadmap_id))
    return Response(status_code=204)


@router.get("/topics")
def list_topics(owner: str = Depends(_owner)) -> dict[str, list[str]]:
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
def import_topics(progress: dict[str, list[str]], owner: str = Depends(_owner)) -> dict[str, int]:
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
def complete_topic(roadmap_id: str, topic_id: str, owner: str = Depends(_owner)) -> dict[str, bool]:
    _check_topic(roadmap_id, topic_id)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO roadmap_topic_progress (owner_hash, roadmap_id, topic_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (owner_hash, roadmap_id, topic_id) DO NOTHING",
            (owner, roadmap_id, topic_id),
        )
    return {"completed": True}


@router.delete("/topics/{roadmap_id}/{topic_id}", status_code=204)
def uncomplete_topic(roadmap_id: str, topic_id: str, owner: str = Depends(_owner)) -> Response:
    _check_topic(roadmap_id, topic_id)
    with _connect() as conn:
        conn.execute(
            "DELETE FROM roadmap_topic_progress WHERE owner_hash = %s AND roadmap_id = %s AND topic_id = %s",
            (owner, roadmap_id, topic_id),
        )
    return Response(status_code=204)


def _application_dict(row) -> dict:
    return {
        "id": str(row[0]), "company": row[1], "role": row[2], "source": row[3],
        "vacancyUrl": row[4] or "", "appliedOn": row[5].isoformat(),
        "responseReceived": row[6], "notes": row[7], "status": row[8],
        "followUpOn": row[9].isoformat() if row[9] else None,
        "contactName": row[10], "contactEmail": row[11],
        "resumeVersionId": str(row[12]) if row[12] else None,
        "jobDescription": row[13], "coverLetter": row[14],
        "recruiterMessage": row[15], "interviewPrep": row[16],
    }


def _application_values(owner: str, application: JobApplicationInput, application_id: UUID) -> tuple:
    return (
        application_id, owner, application.company, application.role, application.source,
        str(application.vacancyUrl or ""), application.appliedOn,
        application.responseReceived, application.notes,
        application.status, application.followUpOn, application.contactName,
        application.contactEmail, application.resumeVersionId,
        application.jobDescription, application.coverLetter,
        application.recruiterMessage, application.interviewPrep,
    )


@router.get("/applications")
def list_applications(owner: str = Depends(_owner)) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, company, role, source, vacancy_url, applied_on, response_received, notes, "
            "status, follow_up_on, contact_name, contact_email, resume_version_id, "
            "job_description, cover_letter, recruiter_message, interview_prep "
            "FROM job_applications WHERE owner_hash = %s ORDER BY applied_on DESC, created_at DESC",
            (owner,),
        ).fetchall()
    return [_application_dict(row) for row in rows]


@router.put("/applications")
def import_applications(applications: list[ImportedJobApplication], owner: str = Depends(_owner)) -> dict[str, int]:
    if len(applications) > 5000:
        raise HTTPException(422, "Há candidaturas demais para importar de uma vez.")
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO job_applications "
                "(id, owner_hash, company, role, source, vacancy_url, applied_on, response_received, notes, "
                "status, follow_up_on, contact_name, contact_email, resume_version_id, "
                "job_description, cover_letter, recruiter_message, interview_prep) "
                "VALUES (" + ", ".join(["%s"] * 18) + ") ON CONFLICT (id) DO NOTHING",
                [_application_values(owner, entry, entry.id) for entry in applications],
            )
    return {"imported": len(applications)}


@router.post("/applications", status_code=201)
def create_application(application: JobApplicationInput, owner: str = Depends(_owner)) -> dict:
    application_id = uuid4()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO job_applications "
            "(id, owner_hash, company, role, source, vacancy_url, applied_on, response_received, notes, "
            "status, follow_up_on, contact_name, contact_email, resume_version_id, "
            "job_description, cover_letter, recruiter_message, interview_prep) "
            "VALUES (" + ", ".join(["%s"] * 18) + ")",
            _application_values(owner, application, application_id),
        )
    return {"id": str(application_id), **application.model_dump(mode="json", exclude={"vacancyUrl"}),
            "vacancyUrl": str(application.vacancyUrl or "")}


@router.put("/applications/{application_id}")
def update_application(application_id: UUID, application: JobApplicationInput,
                       owner: str = Depends(_owner)) -> dict:
    with _connect() as conn:
        updated = conn.execute(
            "UPDATE job_applications SET company = %s, role = %s, source = %s, vacancy_url = %s, "
            "applied_on = %s, response_received = %s, notes = %s, status = %s, follow_up_on = %s, "
            "contact_name = %s, contact_email = %s, resume_version_id = %s, job_description = %s, "
            "cover_letter = %s, recruiter_message = %s, interview_prep = %s, updated_at = now() "
            "WHERE id = %s AND owner_hash = %s RETURNING id",
            (application.company, application.role, application.source,
             str(application.vacancyUrl or ""), application.appliedOn, application.responseReceived,
             application.notes, application.status, application.followUpOn,
             application.contactName, application.contactEmail, application.resumeVersionId,
             application.jobDescription, application.coverLetter,
             application.recruiterMessage, application.interviewPrep, application_id, owner),
        ).fetchone()
    if not updated:
        raise HTTPException(404, "Candidatura não encontrada neste perfil.")
    return {"id": str(application_id), **application.model_dump(mode="json", exclude={"vacancyUrl"}),
            "vacancyUrl": str(application.vacancyUrl or "")}


@router.delete("/applications/{application_id}", status_code=204)
def delete_application(application_id: UUID, owner: str = Depends(_owner)) -> Response:
    with _connect() as conn:
        conn.execute("DELETE FROM job_applications WHERE id = %s AND owner_hash = %s", (application_id, owner))
    return Response(status_code=204)
