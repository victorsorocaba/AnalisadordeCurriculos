from fastapi.testclient import TestClient

from backend.main import app
from backend.services.certifications import recommend_certifications


client = TestClient(app)


def test_recommendations_follow_resume_skills() -> None:
    titles = [item["title"] for item in recommend_certifications("Analista de dados com Power BI, DAX e SQL")]
    assert titles[0] == "Microsoft Certified: Power BI Data Analyst Associate"
    assert "Certified Tester Foundation Level" not in " ".join(titles)


def test_goal_can_direct_recommendations() -> None:
    items = recommend_certifications("Experiência em relatórios", "Quero atuar como Scrum Master")
    assert items[0]["id"] == "psm-i"
    assert "scrum master" in items[0]["matched_terms"]


def test_page_and_text_resume_endpoint() -> None:
    page = client.get("/certificacoes")
    assert page.status_code == 200
    assert 'id="certification-list"' in page.text
    response = client.post(
        "/api/certifications/recommend",
        files={"resume": ("curriculo.txt", b"Desenvolvedor Python e APIs", "text/plain")},
    )
    assert response.status_code == 200
    assert any(item["id"] in {"pcep", "pcap"} for item in response.json()["recommendations"])
    assert "Desenvolvedor Python" not in str(response.json())


def test_resume_validation() -> None:
    assert client.post("/api/certifications/recommend", data={}).status_code == 422
    assert client.post(
        "/api/certifications/recommend",
        files={"resume": ("curriculo.docx", b"test", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).status_code == 415
