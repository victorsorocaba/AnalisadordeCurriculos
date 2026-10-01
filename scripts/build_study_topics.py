"""Build the original learning checklists from a compact, editable source."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "study-topics-source.txt"
CATALOG = ROOT / "frontend" / "roadmaps.json"
OUTPUT = ROOT / "frontend" / "study-topics.json"
PHASES = ("Fundamentos", "Construção", "Prática e qualidade")


def build() -> dict:
    roadmaps = json.loads(CATALOG.read_text(encoding="utf-8"))["roadmaps"]
    names = {roadmap["id"] for roadmap in roadmaps}
    topics_by_route = {}
    for number, raw in enumerate(SOURCE.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        slug, *titles = (part.strip() for part in raw.split("|"))
        if slug in topics_by_route or slug not in names or len(titles) != 12 or len(set(titles)) != 12 or not all(titles):
            raise ValueError(f"Linha {number}: rota ou tópicos inválidos ({slug})")
        sections = []
        for index, phase in enumerate(PHASES):
            phase_topics = []
            for title in titles[index * 4:(index + 1) * 4]:
                topic_id = hashlib.sha256(f"{slug}:{title}".encode()).hexdigest()[:16]
                phase_topics.append({"id": topic_id, "title": title})
            sections.append({"title": phase, "topics": phase_topics})
        topics_by_route[slug] = {"sections": sections, "total": 12}
    missing = names - topics_by_route.keys()
    if missing:
        raise ValueError(f"Rotas sem tópicos: {sorted(missing)}")
    return {"note": "Checklists originais do Alinha; consulte o roadmap.sh para mapas e recursos oficiais.", "roadmaps": topics_by_route}


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Criados tópicos para {len(build()['roadmaps'])} rotas em {OUTPUT}")
