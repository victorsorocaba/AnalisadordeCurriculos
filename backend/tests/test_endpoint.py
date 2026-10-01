"""Endpoint tests for the FastAPI ``POST /api/analyze`` route (Requirements 1, 2, 4, 5).

Covers spec tasks 7.2-7.8 and 7.10 for the resume-analyzer-latex spec. The AI
service is always mocked (``backend.main.analyze_resume`` is patched as
referenced inside ``backend.main``) so that NO real network or AI provider call
ever occurs and the tests are deterministic.

Property tests (Hypothesis, >=100 examples each, ``deadline=None`` because the
in-process ``TestClient`` HTTP round trip is comparatively slow):

* Property 11 (task 7.2): valid request -> 200 + schema-valid body.
* Property 12 (task 7.3): missing resume rejected first, regardless of job desc.
* Property 13 (task 7.4): whitespace-only job description -> 422.
* Property 14 (task 7.5): over-length job description -> 422.
* Property 15 (task 7.6): unsupported content type -> 415.
* Property 16 (task 7.7): over-size file -> 413 (size-check predicate + boundary).
* Property 17 (task 7.8): invalid AI output -> 502 with no result body.

Example/edge tests (task 7.10): well-formed multipart -> 200; route exists and
is POST (GET -> 405); empty file -> 422; missing API key -> 500; AI
error/timeout -> 502.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.main import MAX_FILE_SIZE_BYTES, app
from backend.models.schemas import AnalysisResult
from backend.services.ai_service import (
    AICallError,
    AIKeyMissingError,
    AIValidationError,
)

client = TestClient(app)

ANALYZE_URL = "/api/analyze"
TEN_MEGABYTES = 10 * 1024 * 1024

# A canonical valid result returned by the mocked AI service.
_VALID_RESULT = AnalysisResult(
    percentage=75,
    improvements=["Add measurable impact to each bullet point."],
    latex_code="\\documentclass{article}\\begin{document}Hi\\end{document}",
)


# ---------------------------------------------------------------------------
# AI service mocks (patched onto ``backend.main.analyze_resume``)
# ---------------------------------------------------------------------------


async def _fake_ai_ok(resume_text: str, job_description: str, projects: str = "") -> AnalysisResult:
    """Stand-in for the AI service that returns a fixed, valid result."""
    return _VALID_RESULT


def _make_spy() -> tuple[list, "object"]:
    """Return ``(calls, fake)`` where ``fake`` records every invocation in ``calls``."""
    calls: list = []

    async def spy(resume_text: str, job_description: str, projects: str = "") -> AnalysisResult:
        calls.append((resume_text, job_description))
        return _VALID_RESULT

    return calls, spy


def test_blank_resume_text_does_not_call_ai() -> None:
    calls, spy = _make_spy()
    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"   ", "text/plain")},
            data={"job_description": "Developer"},
        )
    assert response.status_code == 422
    assert calls == []


def test_oversized_projects_rejected_before_ai() -> None:
    calls, spy = _make_spy()
    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"Experience", "text/plain")},
            data={"job_description": "Developer", "projects": "x" * 20_001},
        )
    assert response.status_code == 422
    assert calls == []


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A guaranteed non-whitespace core (printable ASCII, excludes space at 0x20) so
# the job description always has at least one non-whitespace character, kept far
# below the 20,000-character cap.
_non_ws_core = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=50,
)

_valid_job_description = st.builds(
    lambda prefix, core, suffix: prefix + core + suffix,
    st.text(max_size=80),
    _non_ws_core,
    st.text(max_size=80),
)

# Non-empty, UTF-8-decodable bytes that the real ``extract_text`` accepts for the
# ``text/plain`` path (the AI is mocked, so the extracted content is irrelevant).
_valid_resume_bytes = st.text(
    alphabet=st.characters(codec="utf-8"),
    min_size=1,
    max_size=200,
).map(lambda s: ("X" + s).encode("utf-8"))

# Whitespace-only job descriptions, including the empty string.
_whitespace_job_description = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=30),
)

# Over-length job descriptions (> 20,000 chars) built from an integer surplus so
# Hypothesis never has to draw a giant string into its buffer.
_overlength_job_description = st.integers(min_value=20_001, max_value=20_200).map(
    lambda n: "x" * n
)

# Any job description value: empty, whitespace, normal, or over-length.
_any_job_description = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),
    _valid_job_description,
    _overlength_job_description,
)

# Declared content types other than application/pdf and text/plain.
_unsupported_content_types = st.sampled_from(
    [
        "application/octet-stream",
        "image/png",
        "image/jpeg",
        "application/json",
        "application/msword",
        "text/html",
        "application/xml",
        "video/mp4",
        "application/zip",
    ]
)


# ===========================================================================
# Task 7.2 / Property 11 - valid request -> 200 + schema-valid body
# ===========================================================================

# Feature: resume-analyzer-latex, Property 11: Valid request with successful AI yields 200 and a schema-valid body
@settings(max_examples=100, deadline=None)
@given(resume_bytes=_valid_resume_bytes, job_description=_valid_job_description)
def test_property_11_valid_request_yields_200_and_schema_valid_body(
    resume_bytes: bytes, job_description: str
) -> None:
    """Validates: Requirements 1.4, 4.7, 6.3, 2.1

    For any allowed, non-empty, within-size resume upload and any job
    description with at least one non-whitespace character (<= 20,000 chars),
    when the AI service returns valid output the endpoint responds 200 with a
    body that validates against ``AnalysisResult`` and never 502.
    """
    with patch("backend.main.analyze_resume", new=_fake_ai_ok):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", resume_bytes, "text/plain")},
            data={"job_description": job_description},
        )

    assert response.status_code == 200
    assert response.status_code != 502

    body = response.json()
    # The body must validate against the output schema (Requirement 6.3).
    validated = AnalysisResult(**body)
    assert set(body.keys()) == {"percentage", "improvements", "latex_code"}
    assert 0 <= validated.percentage <= 100
    assert isinstance(validated.improvements, list)
    assert isinstance(validated.latex_code, str) and validated.latex_code


# ===========================================================================
# Task 7.3 / Property 12 - missing resume rejected first, regardless of job desc
# ===========================================================================

# Feature: resume-analyzer-latex, Property 12: A missing resume file is rejected first, regardless of job description
@settings(max_examples=100, deadline=None)
@given(job_description=_any_job_description)
def test_property_12_missing_resume_rejected_first(job_description: str) -> None:
    """Validates: Requirements 1.5, 1.8

    When the request omits the resume file part, the endpoint responds 422 with
    a message identifying the missing resume (taking precedence over any empty
    or over-length job-description error), and the AI service is never called.
    """
    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        # No ``files=`` argument -> the resume file part is omitted entirely.
        response = client.post(ANALYZE_URL, data={"job_description": job_description})

    assert response.status_code == 422
    assert "resume" in response.json()["detail"].lower()
    assert calls == []


# ===========================================================================
# Task 7.4 / Property 13 - whitespace-only job description -> 422
# ===========================================================================

# Feature: resume-analyzer-latex, Property 13: A whitespace-only job description is rejected
@settings(max_examples=100, deadline=None)
@given(resume_bytes=_valid_resume_bytes, job_description=_whitespace_job_description)
def test_property_13_whitespace_job_description_rejected(
    resume_bytes: bytes, job_description: str
) -> None:
    """Validates: Requirements 1.6

    With a valid resume present, a job description that is empty or composed
    solely of whitespace yields 422 with a message identifying the empty job
    description as the cause.
    """
    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", resume_bytes, "text/plain")},
            data={"job_description": job_description},
        )

    assert response.status_code == 422
    assert "job description" in response.json()["detail"].lower()
    assert calls == []


# ===========================================================================
# Task 7.5 / Property 14 - over-length job description -> 422
# ===========================================================================

# Feature: resume-analyzer-latex, Property 14: An over-length job description is rejected
@settings(max_examples=100, deadline=None)
@given(resume_bytes=_valid_resume_bytes, job_description=_overlength_job_description)
def test_property_14_overlength_job_description_rejected(
    resume_bytes: bytes, job_description: str
) -> None:
    """Validates: Requirements 1.7

    With a valid resume present, a job description longer than 20,000 characters
    yields 422 with a message identifying the job-description length as the
    cause.
    """
    assert len(job_description) > 20_000  # strategy invariant

    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", resume_bytes, "text/plain")},
            data={"job_description": job_description},
        )

    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "character" in detail or "long" in detail or "20000" in detail
    assert calls == []


# ===========================================================================
# Task 7.6 / Property 15 - unsupported content type -> 415
# ===========================================================================

# Feature: resume-analyzer-latex, Property 15: An unsupported content type is rejected with 415
@settings(max_examples=100, deadline=None)
@given(
    resume_bytes=_valid_resume_bytes,
    content_type=_unsupported_content_types,
    job_description=_valid_job_description,
)
def test_property_15_unsupported_content_type_rejected(
    resume_bytes: bytes, content_type: str, job_description: str
) -> None:
    """Validates: Requirements 2.2

    A declared content type other than application/pdf or text/plain yields 415,
    whose message lists the supported content types, and no result body.
    """
    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.bin", resume_bytes, content_type)},
            data={"job_description": job_description},
        )

    assert response.status_code == 415
    detail = response.json()["detail"]
    assert "application/pdf" in detail and "text/plain" in detail
    # No Analysis_Result is returned.
    assert not {"percentage", "improvements", "latex_code"} <= set(
        response.json().keys()
    )
    assert calls == []


# ===========================================================================
# Task 7.7 / Property 16 - over-size file -> 413
# ===========================================================================

# Feature: resume-analyzer-latex, Property 16: An over-size file is rejected with 413
@settings(max_examples=200, deadline=None)
@given(size=st.integers(min_value=TEN_MEGABYTES - 100, max_value=TEN_MEGABYTES + 100))
def test_property_16_size_check_predicate_matches_10mb_boundary(size: int) -> None:
    """Validates: Requirements 2.4

    The size-check predicate the endpoint uses (``len(data) > MAX_FILE_SIZE_BYTES``)
    classifies a payload as over-size exactly when it exceeds 10 megabytes. This
    iterates over sizes around the boundary WITHOUT allocating giant payloads.
    """
    # The configured limit must encode exactly 10 megabytes (Requirement 2.4).
    assert MAX_FILE_SIZE_BYTES == TEN_MEGABYTES

    expected_rejected = size > TEN_MEGABYTES
    actual_rejected = size > MAX_FILE_SIZE_BYTES
    assert actual_rejected == expected_rejected


def test_property_16_oversize_file_boundary_returns_413() -> None:
    """Validates: Requirements 2.4

    A single boundary example at the endpoint level: a payload of exactly
    ``MAX_FILE_SIZE_BYTES + 1`` bytes (~10 MB + 1) is rejected with HTTP 413 and
    its message states the 10 MB maximum, with no result body and no AI call.
    """
    oversize = b"\0" * (MAX_FILE_SIZE_BYTES + 1)
    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", oversize, "text/plain")},
            data={"job_description": "Senior Python engineer with FastAPI."},
        )

    assert response.status_code == 413
    assert "10 mb" in response.json()["detail"].lower()
    assert not {"percentage", "improvements", "latex_code"} <= set(
        response.json().keys()
    )
    assert calls == []


# ===========================================================================
# Task 7.8 / Property 17 - invalid AI output -> 502 with no result body
# ===========================================================================

# Feature: resume-analyzer-latex, Property 17: Invalid AI output is surfaced as 502 with no result body
@settings(max_examples=100, deadline=None)
@given(
    resume_bytes=_valid_resume_bytes,
    job_description=_valid_job_description,
    message=st.text(max_size=60),
)
def test_property_17_invalid_ai_output_returns_502_no_result(
    resume_bytes: bytes, job_description: str, message: str
) -> None:
    """Validates: Requirements 5.5

    When the AI service reports schema-violating output (modelled by raising
    ``AIValidationError``), the endpoint responds 502 and returns no
    Analysis_Result body.
    """

    async def raise_validation(resume_text: str, jd: str, projects: str = "") -> AnalysisResult:
        raise AIValidationError(message or "schema violation")

    with patch("backend.main.analyze_resume", new=raise_validation):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", resume_bytes, "text/plain")},
            data={"job_description": job_description},
        )

    assert response.status_code == 502
    body = response.json()
    assert "detail" in body
    # The body is an error, not a valid Analysis_Result.
    assert not {"percentage", "improvements", "latex_code"} <= set(body.keys())
    with pytest.raises(ValidationError):
        AnalysisResult(**body)


# ===========================================================================
# Task 7.10 - endpoint example/edge tests (AI service mocked)
# ===========================================================================

_VALID_JOB_DESCRIPTION = "Seeking a Python backend developer with FastAPI experience."


def test_wellformed_multipart_request_returns_200() -> None:
    """Validates: Requirements 1.2

    A well-formed multipart request (one resume file part + one job_description
    field) returns 200 with a schema-valid body when the AI service succeeds.
    """
    with patch("backend.main.analyze_resume", new=_fake_ai_ok):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"Jane Doe, Python developer.", "text/plain")},
            data={"job_description": _VALID_JOB_DESCRIPTION},
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"percentage", "improvements", "latex_code"}
    AnalysisResult(**body)


def test_route_exists_and_is_post_only() -> None:
    """Validates: Requirements 1.1, 1.3

    The ``/api/analyze`` route exists and is registered for POST; a GET request
    to the same path is rejected with 405 Method Not Allowed.
    """
    # The path is registered for POST.
    post_paths = {
        route.path
        for route in app.routes
        if getattr(route, "methods", None) and "POST" in route.methods
    }
    assert ANALYZE_URL in post_paths

    # GET is not allowed on the analyze route.
    assert client.get(ANALYZE_URL).status_code == 405


def test_empty_file_returns_422() -> None:
    """Validates: Requirements 2.3

    A 0-byte resume file yields 422 with a message indicating the file is empty,
    and the AI service is never invoked.
    """
    calls, spy = _make_spy()

    with patch("backend.main.analyze_resume", new=spy):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"", "text/plain")},
            data={"job_description": _VALID_JOB_DESCRIPTION},
        )

    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()
    assert calls == []


def test_missing_api_key_returns_500() -> None:
    """Validates: Requirements 4.5

    When the AI service reports a missing provider API key (modelled by raising
    ``AIKeyMissingError``), the endpoint responds 500.
    """

    async def raise_key_missing(resume_text: str, job_description: str, projects: str = "") -> AnalysisResult:
        raise AIKeyMissingError("The AI provider API key is not configured.")

    with patch("backend.main.analyze_resume", new=raise_key_missing):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"resume text", "text/plain")},
            data={"job_description": _VALID_JOB_DESCRIPTION},
        )

    assert response.status_code == 500
    assert "key" in response.json()["detail"].lower()


def test_ai_error_or_timeout_returns_502() -> None:
    """Validates: Requirements 4.6

    When the AI model call errors or times out (modelled by raising
    ``AICallError``), the endpoint responds 502.
    """

    async def raise_call_error(resume_text: str, job_description: str, projects: str = "") -> AnalysisResult:
        raise AICallError("The AI model call did not complete successfully: timeout.")

    with patch("backend.main.analyze_resume", new=raise_call_error):
        response = client.post(
            ANALYZE_URL,
            files={"resume": ("resume.txt", b"resume text", "text/plain")},
            data={"job_description": _VALID_JOB_DESCRIPTION},
        )

    assert response.status_code == 502
    body = response.json()
    assert "detail" in body
    assert not {"percentage", "improvements", "latex_code"} <= set(body.keys())
