"""Resume text extraction (Requirement 3).

Pure extraction logic for resume documents. Given the raw uploaded bytes and the
declared content type, this module extracts plain text:

- PDF (``application/pdf``): opened in-memory with ``pdfplumber``; the text of
  every page is concatenated in page order, with pages that yield ``None``
  normalized to an empty string (Requirements 3.1, 3.2).
- TXT (``text/plain``): decoded as UTF-8 (Requirement 3.3).

The final result always has leading and trailing whitespace removed
(Requirement 3.4). Any UTF-8 decode failure (TXT) or pdfplumber/PDF parsing
error (PDF) is raised as :class:`ExtractionError`, which ``main.py`` maps to an
HTTP 422 response (Requirements 3.5, 3.6).

This module performs extraction only and never calls the AI service.
"""

from __future__ import annotations

import io

import pdfplumber

PDF_CONTENT_TYPE = "application/pdf"
TXT_CONTENT_TYPE = "text/plain"


class ExtractionError(Exception):
    """Raised when resume text extraction fails.

    Signals a UTF-8 decode failure for a TXT document (Requirement 3.5) or any
    error raised by pdfplumber while parsing a PDF document (Requirement 3.6).
    ``main.py`` maps this to an HTTP 422 response and does not forward the
    document to the AI service.
    """


def extract_text(data: bytes, content_type: str) -> str:
    """Extract plain text from a resume document.

    Args:
        data: The raw bytes of the uploaded resume document.
        content_type: The declared content type, either ``application/pdf`` or
            ``text/plain``.

    Returns:
        The extracted text with leading and trailing whitespace removed. A PDF
        that yields zero readable characters returns an empty string
        (Requirement 3.2).

    Raises:
        ExtractionError: If a TXT document cannot be decoded as UTF-8
            (Requirement 3.5) or pdfplumber raises while processing a PDF
            (Requirement 3.6).
    """
    if content_type == PDF_CONTENT_TYPE:
        text = _extract_pdf(data)
    elif content_type == TXT_CONTENT_TYPE:
        text = _decode_txt(data)
    else:
        raise ExtractionError(f"Unsupported content type for extraction: {content_type!r}")

    return text.strip()


def _extract_pdf(data: bytes) -> str:
    """Concatenate the text of every PDF page in page order.

    Pages whose ``extract_text()`` returns ``None`` are normalized to ``""`` so
    that an image-only or empty PDF yields an empty string rather than an error
    (Requirements 3.1, 3.2).
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any pdfplumber/PDF error -> 422
        raise ExtractionError(f"Failed to extract text from PDF: {exc}") from exc

    return "\n".join(pages)


def _decode_txt(data: bytes) -> str:
    """Decode TXT bytes as UTF-8, raising ``ExtractionError`` on failure."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"Failed to decode TXT document as UTF-8: {exc}") from exc
