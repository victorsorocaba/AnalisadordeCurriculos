"""Rules-based certification suggestions grounded in the user's profile text."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("certification_catalog.json")
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["certifications"]
LEVEL_ORDER = {"Fundamentos": 0, "Intermediário": 1, "Avançado": 2}
GENERIC_TERMS = {"dados", "sql", "cloud", "nuvem", "devops", "infraestrutura", "backend", "api", "python"}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value)


def _matches(text: str, keyword: str) -> bool:
    term = _normalize(keyword)
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))


def recommend_certifications(profile_text: str, goal: str = "", limit: int = 8) -> list[dict]:
    """Rank official credentials using exact skill/role phrases, without an AI call."""
    profile = _normalize(profile_text)
    objective = _normalize(goal)
    ranked = []
    for item in CATALOG:
        profile_hits = [term for term in item["keywords"] if _matches(profile, term)]
        goal_hits = [term for term in item["keywords"] if _matches(objective, term)]
        score = sum(1 if term in GENERIC_TERMS else 2 for term in profile_hits) * 2
        score += sum(1 if term in GENERIC_TERMS else 2 for term in goal_hits) * 3
        if not score:
            continue
        evidence = list(dict.fromkeys(goal_hits + profile_hits))[:4]
        if profile_hits and goal_hits:
            reason = f"O currículo e o objetivo citam {', '.join(evidence)}. {item['focus']}"
        elif profile_hits:
            reason = f"O currículo cita {', '.join(evidence)}. {item['focus']}"
        else:
            reason = f"O objetivo cita {', '.join(evidence)}. {item['focus']}"
        ranked.append({
            "id": item["id"],
            "title": item["title"],
            "provider": item["provider"],
            "level": item["level"],
            "area": item["area"],
            "url": item["url"],
            "reason": reason,
            "matched_terms": evidence,
            "score": score,
        })
    ranked.sort(key=lambda item: (-item["score"], LEVEL_ORDER.get(item["level"], 9), item["title"]))
    return ranked[:limit]
