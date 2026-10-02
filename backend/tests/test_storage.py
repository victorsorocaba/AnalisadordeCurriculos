"""API boundaries for private PostgreSQL storage."""

import base64
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app
from backend import storage


client = TestClient(app)
KEY = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")


def sample_version() -> dict:
    return {
        "id": str(uuid4()), "date": datetime.now(timezone.utc).isoformat(),
        "label": "Vaga Python", "jobDescription": "Python e SQL", "percentage": 80,
        "analysis": {
            "percentage": 80, "improvements": [], "matches": [], "gaps": [],
            "draft": {key: "" for key in (
                "name", "contact", "headline", "summary", "experience",
                "education", "skills", "projects")},
        },
    }


class FakeConnection:
    def __init__(self, rows=(), one=None):
        self.rows = rows
        self.one = one
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one

    def cursor(self):
        return self

    def executemany(self, sql, params):
        self.calls.append((sql, params))


def test_storage_is_optional_and_private(monkeypatch):
    monkeypatch.setattr(storage, "_database_url", lambda: "")
    assert client.get("/api/storage/status").json() == {"enabled": False}
    assert client.get("/api/storage/health").status_code == 503
    assert client.get("/api/storage/versions").status_code == 401
    assert client.get("/api/storage/versions", headers={"X-Profile-Key": KEY}).status_code == 503


def test_versions_are_scoped_to_hashed_profile_key(monkeypatch):
    fake = FakeConnection([(uuid4(), datetime.now(timezone.utc), "A", "Python", 70, {"draft": {}})])
    monkeypatch.setattr(storage, "_connect", lambda: fake)
    response = client.get("/api/storage/versions", headers={"X-Profile-Key": KEY})
    assert response.status_code == 200
    assert response.json()[0]["label"] == "A"
    assert fake.calls[0][1] == (hashlib.sha256(KEY.encode()).hexdigest(),)


def test_version_create_and_delete_use_owner_scope(monkeypatch):
    fake = FakeConnection()
    monkeypatch.setattr(storage, "_connect", lambda: fake)
    version = sample_version()
    response = client.post("/api/storage/versions", headers={"X-Profile-Key": KEY}, json=version)
    assert response.status_code == 201
    assert len(fake.calls) == 2
    assert fake.calls[0][1][1] == hashlib.sha256(KEY.encode()).hexdigest()
    response = client.delete(f"/api/storage/versions/{version['id']}", headers={"X-Profile-Key": KEY})
    assert response.status_code == 204
    assert fake.calls[2][1][1] == hashlib.sha256(KEY.encode()).hexdigest()


def test_invalid_roadmap_status_is_rejected(monkeypatch):
    fake = FakeConnection()
    monkeypatch.setattr(storage, "_connect", lambda: fake)
    response = client.put("/api/storage/roadmaps/python", headers={"X-Profile-Key": KEY}, json={"status": "unknown"})
    assert response.status_code == 422
    assert not fake.calls


def test_topic_progress_is_scoped_and_rejects_unknown_topics(monkeypatch):
    import json
    from pathlib import Path

    catalog = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "study-topics.json").read_text(encoding="utf-8"))
    topic_id = catalog["roadmaps"]["backend"]["sections"][0]["topics"][0]["id"]
    fake = FakeConnection([("backend", topic_id)])
    monkeypatch.setattr(storage, "_connect", lambda: fake)
    headers = {"X-Profile-Key": KEY}
    response = client.get("/api/storage/topics", headers=headers)
    assert response.json() == {"backend": [topic_id]}
    assert fake.calls[0][1] == (hashlib.sha256(KEY.encode()).hexdigest(),)
    response = client.put(f"/api/storage/topics/backend/{topic_id}", headers=headers)
    assert response.status_code == 200
    assert fake.calls[-1][1] == (hashlib.sha256(KEY.encode()).hexdigest(), "backend", topic_id)
    response = client.delete(f"/api/storage/topics/backend/{topic_id}", headers=headers)
    assert response.status_code == 204
    assert fake.calls[-1][1] == (hashlib.sha256(KEY.encode()).hexdigest(), "backend", topic_id)
    call_count = len(fake.calls)
    assert client.put("/api/storage/topics/backend/not-a-topic", headers=headers).status_code == 404
    assert len(fake.calls) == call_count


def test_every_roadmap_has_an_individual_page_and_unique_checklist():
    import json
    from pathlib import Path

    from scripts.build_study_topics import build
    from scripts.build_study_keywords import build as build_keywords

    data = build()["roadmaps"]
    assert len(data) == 95
    assert set(build_keywords()) == set(data)
    assert json.loads((Path(__file__).resolve().parents[2] / "frontend" / "study-keywords.json").read_text(encoding="utf-8")) == build_keywords()
    assert all(len({topic["id"] for section in route["sections"] for topic in section["topics"]}) == 12 for route in data.values())
    assert client.get("/rotas-estudo/backend").status_code == 200
    assert client.get("/rotas-estudo/unknown-route").status_code == 404


def test_job_applications_validate_and_scope_profile(monkeypatch):
    application_id = uuid4()
    record = {
        "company": "Empresa ABC", "role": "Desenvolvedor Backend", "source": "LinkedIn",
        "vacancyUrl": "https://example.com/vaga", "appliedOn": "2026-10-02",
        "responseReceived": False, "notes": "",
    }
    fake = FakeConnection(rows=[(application_id, "Empresa ABC", "Desenvolvedor Backend", "LinkedIn",
                                "https://example.com/vaga", date(2026, 10, 2), False, "")], one=(application_id,))
    monkeypatch.setattr(storage, "_connect", lambda: fake)
    headers = {"X-Profile-Key": KEY}
    assert client.get("/api/storage/applications").status_code == 401
    assert client.post("/api/storage/applications", headers=headers, json={**record, "company": " "}).status_code == 422
    assert client.post("/api/storage/applications", headers=headers, json={**record, "vacancyUrl": "javascript:alert(1)"}).status_code == 422
    assert client.get("/candidaturas").status_code == 200
    assert client.get("/api/storage/applications", headers=headers).json()[0]["appliedOn"] == "2026-10-02"
    assert fake.calls[-1][1] == (hashlib.sha256(KEY.encode()).hexdigest(),)
    created = client.post("/api/storage/applications", headers=headers, json=record)
    assert created.status_code == 201
    assert fake.calls[-1][1][1] == hashlib.sha256(KEY.encode()).hexdigest()
    updated = client.put(f"/api/storage/applications/{application_id}", headers=headers,
                         json={**record, "responseReceived": True})
    assert updated.status_code == 200
    assert updated.json()["responseReceived"] is True
    assert fake.calls[-1][1][-1] == hashlib.sha256(KEY.encode()).hexdigest()
    deleted = client.delete(f"/api/storage/applications/{application_id}", headers=headers)
    assert deleted.status_code == 204
    assert fake.calls[-1][1] == (application_id, hashlib.sha256(KEY.encode()).hexdigest())
