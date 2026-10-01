"""Build curated résumé keyword suggestions for every study route."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "study-keywords-source.txt"
CATALOG = ROOT / "frontend" / "roadmaps.json"
OUTPUT = ROOT / "frontend" / "study-keywords.json"


def build() -> dict[str, list[str]]:
    expected = {item["id"] for item in json.loads(CATALOG.read_text(encoding="utf-8"))["roadmaps"]}
    result = {}
    for number, raw in enumerate(SOURCE.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        slug, *terms = (value.strip() for value in raw.split("|"))
        if slug not in expected or slug in result or len(terms) != 6 or len(set(terms)) != 6 or not all(terms):
            raise ValueError(f"Linha {number}: palavras-chave inválidas ({slug})")
        result[slug] = terms
    if set(result) != expected:
        raise ValueError(f"Rotas sem palavras-chave: {sorted(expected - set(result))}")
    return result


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Criadas palavras-chave para {len(build())} rotas em {OUTPUT}")
