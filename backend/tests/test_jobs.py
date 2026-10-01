"""Job discovery from supported provider responses."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.detailed import ResumeDraft
from backend.services.job_search import _listing


client = TestClient(app)


def profile() -> ResumeDraft:
    return ResumeDraft(
        name="Ana", contact="ana@example.com", headline="Desenvolvedora Python",
        summary="APIs REST", experience="Automatizou relatórios com Python.",
        education="Tecnologia em Sistemas", skills="Python\nDjango\nSQL", projects="",
    )


def test_jobs_search_ranks_supported_skills_and_rejects_unsafe_links(monkeypatch) -> None:
    monkeypatch.delenv("JOOBLE_BR_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    himalayas = [
        {"title": "Python Developer", "companyName": "Acme", "locationRestrictions": ["Brazil"],
         "description": "Python Django SQL", "applicationLink": "https://himalayas.app/jobs/123", "pubDate": 1},
        {"title": "Python Developer", "companyName": "Bad", "locationRestrictions": ["Brazil"],
         "description": "Python", "applicationLink": "javascript:alert(1)"},
    ]
    remotive = [
        {"title": "Python Engineer", "company_name": "Other", "candidate_required_location": "Worldwide",
         "description": "Python API", "url": "https://remotive.com/jobs/123"},
        {"title": "Python Engineer", "company_name": "US Only", "candidate_required_location": "USA only",
         "description": "Python", "url": "https://remotive.com/jobs/456"},
    ]
    with patch("backend.services.job_search._himalayas", new=AsyncMock(return_value=himalayas)), \
         patch("backend.services.job_search._remotive", new=AsyncMock(return_value=remotive)):
        response = client.post("/api/jobs/search", json={"draft": profile().model_dump()})
    assert response.status_code == 200
    body = response.json()
    assert [job["company"] for job in body["jobs"]] == ["Acme", "Other"]
    assert body["jobs"][0]["matched_terms"] == ["Python", "Django", "SQL"]
    assert body["sources"] == ["Himalayas", "Remotive"]
    assert "Vagas locais exigem" in body["notices"][0]


def test_jobs_search_uses_local_providers_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("JOOBLE_BR_API_KEY", "fake")
    monkeypatch.setenv("ADZUNA_APP_ID", "fake")
    monkeypatch.setenv("ADZUNA_APP_KEY", "fake")
    jooble = [{"title": "Desenvolvedora Python", "company": "Empresa A", "location": "Sorocaba",
               "snippet": "Python Django", "link": "https://br.jooble.org/jdp/123"}]
    adzuna = [{"title": "Python Engineer", "company": {"display_name": "Empresa B"},
               "location": {"display_name": "Sorocaba"}, "description": "Python SQL",
               "redirect_url": "https://www.adzuna.com.br/jobs/123"}]
    with patch("backend.services.job_search._jooble", new=AsyncMock(return_value=jooble)), \
         patch("backend.services.job_search._adzuna", new=AsyncMock(return_value=adzuna)):
        response = client.post("/api/jobs/search", json={
            "draft": profile().model_dump(), "work_mode": "local", "location": "Sorocaba, SP",
        })
    assert response.status_code == 200
    assert {job["source"] for job in response.json()["jobs"]} == {"Jooble", "Adzuna"}
    assert response.json()["sources"] == ["Jooble", "Adzuna"]


def test_one_provider_failure_keeps_other_results(monkeypatch) -> None:
    monkeypatch.delenv("JOOBLE_BR_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    with patch("backend.services.job_search._himalayas", new=AsyncMock(side_effect=RuntimeError("offline"))), \
         patch("backend.services.job_search._remotive", new=AsyncMock(return_value=[
             {"title": "Python Engineer", "company_name": "Acme", "candidate_required_location": "Brazil",
              "description": "Python", "url": "https://remotive.com/jobs/1"},
         ])):
        response = client.post("/api/jobs/search", json={"draft": profile().model_dump(), "work_mode": "remote"})
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1
    assert response.json()["sources"] == ["Remotive"]
    assert "Himalayas: busca temporariamente indisponível." in response.json()["notices"]


def test_invalid_provider_link_is_discarded() -> None:
    assert _listing("Jooble", {"title": "Python", "link": "http://example.com"}) is None


def test_entry_level_profile_excludes_senior_and_unrelated_titles(monkeypatch) -> None:
    monkeypatch.delenv("JOOBLE_BR_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    draft = profile()
    draft.headline = "Estagiária em desenvolvimento Python"
    listings = [
        {"title": "Senior Python Engineer", "companyName": "Senior Co", "seniority": ["Senior"],
         "description": "Python", "applicationLink": "https://himalayas.app/jobs/senior"},
        {"title": "React Developer", "companyName": "React Co", "seniority": [],
         "description": "Python Django SQL", "applicationLink": "https://himalayas.app/jobs/react"},
        {"title": "Python Developer", "companyName": "Junior Co", "seniority": [],
         "description": "Python Django", "applicationLink": "https://himalayas.app/jobs/junior"},
    ]
    with patch("backend.services.job_search._himalayas", new=AsyncMock(return_value=listings)), \
         patch("backend.services.job_search._remotive", new=AsyncMock(return_value=[])):
        response = client.post("/api/jobs/search", json={"draft": draft.model_dump(), "work_mode": "remote"})
    assert [job["company"] for job in response.json()["jobs"]] == ["Junior Co"]


def test_jobs_search_respects_configured_access_code(monkeypatch) -> None:
    monkeypatch.setenv("APP_ACCESS_TOKEN", "test-access")
    response = client.post("/api/jobs/search", json={"draft": profile().model_dump()})
    assert response.status_code == 401
