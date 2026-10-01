"""Tests for the detailed analysis and compiled preview."""

import base64
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.detailed import DetailedAnalysis, ResumeDraft
from backend.services.detailed_service import _parse_detailed, _prompt, analyze_detailed
from backend.services.resume_renderer import build_latex


client = TestClient(app)


def sample_draft() -> ResumeDraft:
    return ResumeDraft(
        name="Ana Silva", contact="ana@example.com", headline="Desenvolvedora Python",
        summary="Experiência com APIs & dados.", experience="Criou API em Python",
        education="Bacharelado em Computação", skills="Python e SQL", projects="",
    )


def test_detailed_prompt_uses_star_without_inventing_results() -> None:
    prompt = _prompt("Experiência em Python", "Vaga de desenvolvimento", "")
    assert "método STAR" in prompt
    assert "Situação" in prompt and "Tarefa" in prompt
    assert "Ação" in prompt and "Resultado" in prompt
    assert "Não invente métricas, resultados" in prompt
    assert "Experiência em Python" in prompt


def test_tailor_prompt_uses_only_supported_job_keywords() -> None:
    prompt = _prompt("Python", "Python e AWS", "", tailor_mode=True)
    assert "palavras-chave da vaga que tenham evidência" in prompt
    assert "não acrescente requisitos sem evidência" in prompt
    assert "Em gaps, mostre requisitos importantes" in prompt


def test_tailor_endpoint_preserves_candidate_facts() -> None:
    original = sample_draft()
    tailored = sample_draft()
    tailored.name = "Nome inventado"
    tailored.contact = "contato inventado"
    tailored.education = "Formação inventada"
    tailored.skills = "AWS"
    tailored.summary = "Desenvolvedora Python com experiência em APIs."
    result = DetailedAnalysis(
        percentage=72, improvements=[], matches=[], gaps=["AWS sem evidência"], draft=tailored,
    )
    with patch("backend.main.analyze_detailed", new=AsyncMock(return_value=result)) as mocked:
        response = client.post("/api/tailor", json={
            "draft": original.model_dump(), "job_description": "Python e AWS",
        })
    assert response.status_code == 200
    output = response.json()
    assert output["draft"]["name"] == original.name
    assert output["draft"]["contact"] == original.contact
    assert output["draft"]["education"] == original.education
    assert output["draft"]["skills"] == original.skills
    assert output["draft"]["summary"] == tailored.summary
    assert output["gaps"] == ["AWS sem evidência"]
    assert mocked.await_args.kwargs["tailor_mode"] is True


def test_tailor_endpoint_validates_job_and_access_token(monkeypatch) -> None:
    payload = {"draft": sample_draft().model_dump(), "job_description": "  "}
    assert client.post("/api/tailor", json=payload).status_code == 422
    monkeypatch.setenv("APP_ACCESS_TOKEN", "example-secret")
    payload["job_description"] = "Python"
    assert client.post("/api/tailor", json=payload).status_code == 401


def test_render_compiles_pdf_and_escapes_user_text() -> None:
    draft = sample_draft()
    draft.summary = r"Experiência com 50% de APIs & \input{secret.txt}"
    response = client.post("/api/render", json=draft.model_dump())
    assert response.status_code == 200
    body = response.json()
    assert base64.b64decode(body["pdf_base64"]).startswith(b"%PDF-")
    assert body["preview_pages"]
    assert base64.b64decode(body["preview_pages"][0]).startswith(b"\x89PNG\r\n\x1a\n")
    assert r"\input{secret.txt}" not in body["latex_code"]
    assert r"50\%" in body["latex_code"]


def test_build_latex_omits_empty_sections() -> None:
    source = build_latex(sample_draft())
    assert r"\section*{Projetos}" not in source
    assert r"\section*{Experiência}" in source


def test_experience_heading_and_star_bullets_are_separate() -> None:
    draft = sample_draft()
    draft.experience = (
        "Empresa A | Desenvolvedora | 2023-2025\n"
        "Para reduzir o tempo de atendimento, automatizou triagem e diminuiu a espera em 20%.\n"
        "Empresa B | Analista | 2022\n"
        "Organizou relatórios para apoiar a equipe."
    )
    source = build_latex(draft)
    assert r"\textbf{Empresa A | Desenvolvedora | 2023-2025}\par" in source
    assert r"\textbf{Empresa B | Analista | 2022}\par" in source
    assert r"\item Para reduzir o tempo" in source
    assert r"\item Empresa A" not in source
    assert source.count(r"\begin{itemize}") == source.count(r"\end{itemize}")


def test_detailed_endpoint_returns_editable_analysis() -> None:
    result = DetailedAnalysis(
        percentage=78, improvements=["Quantifique resultados."],
        matches=[{"requirement": "Python", "excerpt": "Python"}], gaps=["Cloud"], draft=sample_draft(),
    )
    with patch("backend.main.analyze_detailed", new=AsyncMock(return_value=result)):
        response = client.post(
            "/api/analyze/detailed",
            files={"resume": ("cv.txt", b"Python experience", "text/plain")},
            data={"job_description": "Python and Cloud"},
        )
    assert response.status_code == 200
    assert response.json()["draft"]["name"] == "Ana Silva"
    assert response.json()["matches"][0]["excerpt"] == "Python"


def test_unverified_match_is_removed() -> None:
    data = {
        "percentage": 60, "improvements": [], "gaps": [],
        "matches": [
            {"requirement": "Python", "excerpt": "Python"},
            {"requirement": "AWS", "excerpt": "AWS"},
        ],
        "draft": sample_draft().model_dump(),
    }
    reply = type("Reply", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": json.dumps(data)})()})()]})()
    with patch("backend.services.detailed_service._resolve_provider", return_value="openai"), \
         patch("backend.services.detailed_service._resolve_api_key", return_value="test"), \
         patch("backend.services.detailed_service._resolve_model", return_value="gpt-4o-mini"), \
         patch("backend.services.detailed_service.AsyncOpenAI") as client_mock:
        client_mock.return_value.chat.completions.create = AsyncMock(return_value=reply)
        import asyncio
        result = asyncio.run(analyze_detailed("Experiência com Python", "Python e AWS"))
    assert [match.requirement for match in result.matches] == ["Python"]


def test_optional_access_code_protects_paid_routes(monkeypatch) -> None:
    monkeypatch.setenv("APP_ACCESS_TOKEN", "example-secret")
    assert client.get("/api/config").json() == {"auth_required": True}
    assert client.post("/api/render", json=sample_draft().model_dump()).status_code == 401
    response = client.post("/api/render", json=sample_draft().model_dump(), headers={"X-Access-Token": "example-secret"})
    assert response.status_code == 200


def test_access_code_limits_analysis_calls(monkeypatch) -> None:
    from backend.main import _rate_events

    monkeypatch.setenv("APP_ACCESS_TOKEN", "example-secret")
    _rate_events.clear()
    for _ in range(10):
        response = client.post("/api/analyze/detailed", headers={"X-Access-Token": "example-secret"})
        assert response.status_code == 422
    response = client.post("/api/analyze/detailed", headers={"X-Access-Token": "example-secret"})
    assert response.status_code == 429
    _rate_events.clear()


def test_google_call_requests_json_schema() -> None:
    import asyncio
    from backend.services.detailed_service import _SCHEMA

    data = {"percentage": 70, "improvements": [], "matches": [], "gaps": [], "draft": sample_draft().model_dump()}
    reply = type("Reply", (), {"text": json.dumps(data)})()
    with patch("backend.services.detailed_service._resolve_provider", return_value="google"), \
         patch("backend.services.detailed_service._resolve_api_key", return_value="test"), \
         patch("backend.services.detailed_service._resolve_model", return_value="gemini-3.6-flash"), \
         patch("backend.services.detailed_service.genai.Client") as client_mock:
        call = AsyncMock(return_value=reply)
        client_mock.return_value.aio.models.generate_content = call
        result = asyncio.run(analyze_detailed("Python", "Python"))
    assert result.percentage == 70
    assert call.call_args.kwargs["config"].response_json_schema == _SCHEMA


def test_detailed_parser_normalizes_harmless_model_variations() -> None:
    draft = sample_draft().model_dump()
    draft.pop("projects")
    draft["summary"] = "A" * 3500
    raw = json.dumps({
        "percentage": "75", "improvements": ["Ajuste"] * 20,
        "matches": [{"requirement": "Python", "excerpt": "Python", "extra": "ignored"}] * 20,
        "gaps": [], "draft": draft, "extra": "ignored",
    })
    result = _parse_detailed("```json\n" + raw + "\n```")
    assert result.percentage == 75
    assert len(result.improvements) == 15
    assert len(result.matches) == 15
    assert len(result.draft.summary) == 3000
    assert result.draft.projects == ""
