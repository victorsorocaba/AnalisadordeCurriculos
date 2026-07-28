"""Tests for the resume Text_Extractor (Requirement 3).

Covers tasks 4.2-4.7 of the resume-analyzer-latex spec:

- Property 7 (task 4.2): TXT extraction is a UTF-8 round-trip.
- Property 8 (task 4.3): PDF extraction concatenates content from all pages.
- Property 9 (task 4.4): Extractor output never has leading/trailing whitespace.
- Unit test (task 4.5, Req 11.1): PDF extraction returns the known content.
- Unit test (task 4.6, Req 11.2): TXT extraction returns trimmed UTF-8 content.
- Edge cases (task 4.7): blank/image-only PDF returns "" (Req 3.2) and malformed
  PDF bytes raise ExtractionError (Req 3.6).

In-memory PDFs are built with reportlab so the tests need no fixture files.
"""

from __future__ import annotations

import io
import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.services.text_extractor import ExtractionError, extract_text

PDF_CONTENT_TYPE = "application/pdf"
TXT_CONTENT_TYPE = "text/plain"


def _make_pdf(pages: list[str]) -> bytes:
    """Render one string per page into an in-memory PDF and return its bytes.

    Each non-empty page string is drawn once; an empty string produces a blank
    (text-free) page, which is used to exercise the image-only/empty-PDF case.
    """
    buffer = io.BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=letter)
    for page_text in pages:
        if page_text:
            pdf_canvas.drawString(72, 720, page_text)
        pdf_canvas.showPage()
    pdf_canvas.save()
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

# UTF-8 encodable characters only (excludes lone surrogates that cannot be
# encoded), so the encode step never fails for the round-trip property.
_utf8_text = st.text(alphabet=st.characters(codec="utf-8"))


# Feature: resume-analyzer-latex, Property 7: TXT extraction is a UTF-8 round-trip
@settings(max_examples=200)
@given(s=_utf8_text)
def test_property_7_txt_extraction_is_utf8_round_trip(s: str) -> None:
    """Validates: Requirements 3.3, 3.4

    Encoding any Unicode string as UTF-8 bytes and extracting it as text/plain
    returns the original string with leading/trailing whitespace removed.
    """
    extracted = extract_text(s.encode("utf-8"), TXT_CONTENT_TYPE)
    assert extracted == s.strip()


# Tokens reportlab renders and pdfplumber re-extracts reliably: contiguous
# uppercase letters (no spaces, no layout ambiguity).
_token = st.text(alphabet=string.ascii_uppercase, min_size=4, max_size=10)


# Feature: resume-analyzer-latex, Property 8: PDF extraction concatenates content from all pages
@settings(max_examples=100, deadline=None)
@given(tokens=st.lists(_token, min_size=1, max_size=4, unique=True))
def test_property_8_pdf_extraction_concatenates_pages(tokens: list[str]) -> None:
    """Validates: Requirements 3.1

    Every page's content appears in the extracted text, in page order. Each
    page's marker is the token suffixed with its (single-digit) page index, so
    markers are mutually non-substring and uniquely locatable with ``find``.
    """
    page_texts = [f"{token}{index}" for index, token in enumerate(tokens)]

    pdf_bytes = _make_pdf(page_texts)
    extracted = extract_text(pdf_bytes, PDF_CONTENT_TYPE)

    last_index = -1
    for marker in page_texts:
        found_index = extracted.find(marker)
        assert found_index != -1, f"page marker {marker!r} missing from extraction: {extracted!r}"
        assert found_index > last_index, (
            f"page marker {marker!r} out of page order in extraction: {extracted!r}"
        )
        last_index = found_index


# Feature: resume-analyzer-latex, Property 9: Extractor output never has leading or trailing whitespace
@settings(max_examples=200)
@given(s=_utf8_text)
def test_property_9_extractor_output_has_no_surrounding_whitespace(s: str) -> None:
    """Validates: Requirements 3.4, 3.2

    The returned text equals itself with leading/trailing whitespace removed,
    i.e. the extractor never returns surrounding whitespace.
    """
    extracted = extract_text(s.encode("utf-8"), TXT_CONTENT_TYPE)
    assert extracted == extracted.strip()


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_pdf_extraction_returns_known_content() -> None:
    """Validates: Requirement 11.1

    Given a PDF containing known text, the extractor returns text containing
    that content.
    """
    pdf_bytes = _make_pdf(["Experienced Python Developer"])

    extracted = extract_text(pdf_bytes, PDF_CONTENT_TYPE)

    for word in ("Experienced", "Python", "Developer"):
        assert word in extracted


def test_txt_extraction_returns_trimmed_utf8_content() -> None:
    """Validates: Requirement 11.2

    Given known UTF-8 bytes with surrounding whitespace, the extractor returns
    the content with leading and trailing whitespace removed.
    """
    content = "Resume content with UTF-8 chars: café résumé naïve"
    raw = ("  \n\t" + content + "  \n\n").encode("utf-8")

    extracted = extract_text(raw, TXT_CONTENT_TYPE)

    assert extracted == content


# ---------------------------------------------------------------------------
# Edge-case tests (task 4.7)
# ---------------------------------------------------------------------------


def test_blank_pdf_returns_empty_string() -> None:
    """Validates: Requirement 3.2

    A blank/image-only PDF (zero readable characters) is treated as a successful
    extraction that returns an empty string.
    """
    pdf_bytes = _make_pdf([""])

    assert extract_text(pdf_bytes, PDF_CONTENT_TYPE) == ""


@pytest.mark.parametrize(
    "bad_bytes",
    [b"%PDF-not-a-real-pdf", b"not a pdf at all"],
)
def test_malformed_pdf_bytes_raise_extraction_error(bad_bytes: bytes) -> None:
    """Validates: Requirement 3.6

    Clearly invalid PDF bytes cause the extractor to raise ExtractionError.
    """
    with pytest.raises(ExtractionError):
        extract_text(bad_bytes, PDF_CONTENT_TYPE)


# ---------------------------------------------------------------------------
# Task 7.9 / Property 10 - invalid UTF-8 TXT input rejected without calling AI
# ---------------------------------------------------------------------------
#
# This endpoint-level property lives here (rather than in test_endpoint.py) per
# the design's Test Organization: it exercises the TXT UTF-8 decode failure path
# (Requirement 3.5) end-to-end through the route. The AI service is replaced by
# a spy so we can assert it is NEVER invoked. No real network/AI call occurs.

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import backend.main as backend_main  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models.schemas import AnalysisResult  # noqa: E402

_endpoint_client = TestClient(app)

# Byte sequences that are NOT valid UTF-8. ``st.binary`` is filtered so that
# decoding as UTF-8 raises, guaranteeing we exercise the decode-failure path.
_invalid_utf8_bytes = st.binary(min_size=1, max_size=64).filter(
    lambda b: not _is_valid_utf8(b)
)


def _is_valid_utf8(data: bytes) -> bool:
    """Return True if ``data`` decodes cleanly as UTF-8, False otherwise."""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# Feature: resume-analyzer-latex, Property 10: Invalid UTF-8 TXT input is rejected without calling the AI
@settings(max_examples=100, deadline=None)
@given(bad_bytes=_invalid_utf8_bytes)
def test_property_10_invalid_utf8_txt_rejected_without_calling_ai(
    bad_bytes: bytes,
) -> None:
    """Validates: Requirements 3.5

    Submitting non-UTF-8 bytes as a ``text/plain`` resume causes the endpoint to
    respond with HTTP 422, and the AI service is never invoked.
    """
    assert not _is_valid_utf8(bad_bytes)  # strategy invariant

    ai_calls: list = []

    async def ai_spy(resume_text: str, job_description: str) -> AnalysisResult:
        ai_calls.append((resume_text, job_description))
        return AnalysisResult(
            percentage=50, improvements=[], latex_code="\\documentclass{article}"
        )

    with patch.object(backend_main, "analyze_resume", new=ai_spy):
        response = _endpoint_client.post(
            "/api/analyze",
            files={"resume": ("resume.txt", bad_bytes, "text/plain")},
            data={"job_description": "Senior Python engineer with FastAPI."},
        )

    assert response.status_code == 422
    assert ai_calls == []
