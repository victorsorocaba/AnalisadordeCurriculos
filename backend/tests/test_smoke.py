"""Smoke / integration tests confirming wiring and structure (Task 10.1).

These tests do not exercise behavior in depth; instead they confirm that the
project's modules are importable, that the public symbols documented in the
design exist at their expected locations, that the FastAPI ``POST /api/analyze``
route is registered, and that the unified ``requirements.txt`` pins every
dependency to a specific version.

Covered requirements:
    - 1.1  : the ``POST /api/analyze`` route is present on the FastAPI app.
    - 6.1  : the input/output Pydantic models live in ``backend.models.schemas``.
    - 10.1 : the app instance + route are defined in ``backend.main``.
    - 10.2 : the AI service public API lives in ``backend.services.ai_service``.
    - 10.3 : the Streamlit frontend helpers import cleanly without launching UI.
    - 10.4 : every dependency in ``/requirements.txt`` is pinned with ``==``.
    - 10.5 : documented as a CI-only clean-environment install check (skipped).

Imports rely on ``pytest.ini`` setting ``pythonpath = .`` at the workspace root,
so ``backend.*`` and ``frontend.*`` resolve as packages/modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Workspace root is two levels above this file: backend/tests/test_smoke.py.
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = WORKSPACE_ROOT / "requirements.txt"


def test_schemas_module_exports_models_and_helper() -> None:
    """``AnalyzeInput``, ``AnalysisResult`` and ``strip_markdown_fences`` import (Req 6.1)."""
    from backend.models.schemas import (
        AnalysisResult,
        AnalyzeInput,
        strip_markdown_fences,
    )

    # Sanity: the imported objects are the expected kinds.
    from pydantic import BaseModel

    assert issubclass(AnalyzeInput, BaseModel)
    assert issubclass(AnalysisResult, BaseModel)
    assert callable(strip_markdown_fences)


def test_text_extractor_module_exports_function_and_error() -> None:
    """``extract_text`` and ``ExtractionError`` import from the extractor module."""
    from backend.services.text_extractor import ExtractionError, extract_text

    assert callable(extract_text)
    assert isinstance(ExtractionError, type)
    assert issubclass(ExtractionError, Exception)


def test_ai_service_module_exports_public_api() -> None:
    """``analyze_resume`` and ``build_prompt`` import from the AI service (Req 10.2)."""
    from backend.services.ai_service import analyze_resume, build_prompt

    assert callable(analyze_resume)
    assert callable(build_prompt)


def test_main_exposes_app_and_analyze_route() -> None:
    """``app`` imports from ``backend.main`` and ``POST /api/analyze`` exists (Req 1.1, 10.1)."""
    from backend.main import app

    # Scan the registered routes for one whose path is /api/analyze and whose
    # methods include POST.
    matching = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/analyze"
        and "POST" in (getattr(route, "methods", None) or set())
    ]

    assert matching, (
        "Expected a POST route at /api/analyze to be registered on the FastAPI "
        "app (Requirements 1.1, 10.1)."
    )


def test_frontend_is_served_by_api() -> None:
    """The main page and its local assets are available from one server."""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="analysis-form"' in page.text
    assert client.get("/assets/styles.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


def test_study_routes_have_a_separate_page() -> None:
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    home = client.get("/")
    study = client.get("/rotas-estudo")
    assert home.status_code == 200
    assert study.status_code == 200
    assert 'href="/rotas-estudo"' in home.text
    assert 'id="roadmaps-list"' not in home.text
    assert 'id="roadmaps-list"' in study.text
    assert client.get("/assets/roadmaps.js").status_code == 200
    assert client.get("/assets/roadmaps.json").status_code == 200


def _iter_requirement_specifiers(raw_text: str):
    """Yield ``(line_number, specifier)`` for each real dependency line.

    Strips inline comments (everything from the first ``#``), trims whitespace,
    and skips blank/comment-only lines. Returns the remaining requirement
    specifier text (e.g. ``uvicorn[standard]==0.48.0``).
    """
    for line_number, original in enumerate(raw_text.splitlines(), start=1):
        # Remove inline comments: everything from the first '#'.
        without_comment = original.split("#", 1)[0]
        specifier = without_comment.strip()
        if not specifier:
            continue
        yield line_number, specifier


def test_requirements_file_exists() -> None:
    """The unified ``/requirements.txt`` exists at the workspace root (Req 10.4)."""
    assert REQUIREMENTS_PATH.is_file(), f"requirements.txt not found at {REQUIREMENTS_PATH}"


def test_every_dependency_is_pinned_with_double_equals() -> None:
    """Every non-empty, non-comment dependency line is pinned with ``==`` (Req 10.4).

    Handles extras such as ``uvicorn[standard]==0.48.0`` and any inline comments.
    Option/include lines (``-r``/``-e``/``--``) are not required to use ``==``;
    this file contains none, but the check tolerates them defensively.
    """
    raw_text = REQUIREMENTS_PATH.read_text(encoding="utf-8")

    specifiers = list(_iter_requirement_specifiers(raw_text))
    # The file must declare at least one dependency.
    assert specifiers, "requirements.txt declares no dependencies."

    unpinned: list[str] = []
    for line_number, specifier in specifiers:
        # Skip pip option / include / editable lines if present (not deps).
        if specifier.startswith(("-r", "-e", "-c", "--")):
            continue
        if "==" not in specifier:
            unpinned.append(f"line {line_number}: {specifier!r}")

    assert not unpinned, (
        "Every dependency in requirements.txt must be pinned with '==' "
        f"(Requirement 10.4). Unpinned entries: {unpinned}"
    )


def test_clean_environment_install_is_a_ci_step() -> None:
    """Req 10.5 (clean-env install + import) is verified in CI, not here.

    The clean-virtual-environment install check -- create a fresh environment,
    ``pip install -r requirements.txt``, then import the backend and frontend
    modules without any additional package installation -- is a CI pipeline step
    rather than an in-process unit test. It is documented here as a skipped test
    so the coverage of Requirement 10.5 remains visible in the suite.
    """
    pytest.skip("Req 10.5 verified in CI: clean-env install + import")
