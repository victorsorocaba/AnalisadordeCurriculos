"""FastAPI application and routing for the resume-analyzer-latex backend.

This module defines the FastAPI ``app`` instance and registers the single
asynchronous ``POST /api/analyze`` route (Requirements 1.1, 10.1). The route
handler enforces a precedence-ordered validation pipeline and then orchestrates
the call sequence ``validate -> extract_text -> analyze_resume -> return`` so
that invalid requests fail fast and cheaply before any extraction or paid AI
call occurs.

Validation pipeline (executed in this exact order to honor Requirement 1.8):

    1. Missing resume                       -> 422 (Req 1.5, 1.8)
    2. Missing/whitespace-only job desc.    -> 422 (Req 1.6)
    3. Job description > 20,000 chars       -> 422 (Req 1.7)
    4. Unsupported content type             -> 415 (Req 2.2)
    5. File > 10 MB                         -> 413 (Req 2.4)
    6. Empty file (0 bytes)                 -> 422 (Req 2.3)
    7. Extraction/decode error              -> 422 (Req 3.5, 3.6)
    8. API key missing                      -> 500 (Req 4.5)
    9. AI error/timeout                     -> 502 (Req 4.6)
   10. AI output fails validation           -> 502 (Req 5.5)

SECURITY NOTE: This endpoint is intentionally UNAUTHENTICATED per the design.
Because each successful request triggers a paid AI provider call, authentication
and rate limiting MUST be added before any public deployment to prevent abuse
and uncontrolled cost.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from backend.models.schemas import AnalysisResult
from backend.services.ai_service import (
    AICallError,
    AIKeyMissingError,
    AIValidationError,
    analyze_resume,
)
from backend.services.text_extractor import ExtractionError, extract_text

# Load environment variables (e.g. AI_PROVIDER, OPENAI_API_KEY) at import time so
# the AI service can read its configuration from the environment (Requirement 4.3).
load_dotenv()

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

#: Maximum allowed job description length in characters (Requirements 1.2, 1.7).
MAX_JOB_DESCRIPTION_CHARS = 20_000

#: Maximum allowed resume file size in bytes: 10 megabytes (Requirement 2.4).
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

#: Content types accepted for the uploaded resume document (Requirements 2.1, 2.2).
SUPPORTED_CONTENT_TYPES = ("application/pdf", "text/plain")


app = FastAPI(title="Resume Analyzer + LaTeX Generator")


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(
    resume: UploadFile | None = File(default=None),
    job_description: str | None = Form(default=None),
    projects: str | None = Form(default=None),
) -> AnalysisResult:
    """Analyze a resume against a job description and return a structured result.

    Accepts a multipart request containing exactly one uploaded resume file part
    and one ``job_description`` text field (Requirements 1.2, 1.3). The request
    is validated in precedence order (Requirement 1.8); on success the resume
    text is extracted and sent to the AI service, and the validated
    :class:`AnalysisResult` is returned with HTTP 200 (Requirement 1.4).

    Raises:
        HTTPException: With the appropriate status code for each failure mode,
            carrying a descriptive ``detail`` message.
    """
    # Step 1: Missing resume file part -> 422 (Requirements 1.5, 1.8).
    # Checked first so it takes precedence over an empty job description.
    if resume is None:
        raise HTTPException(
            status_code=422,
            detail="A resume file is required but was not provided.",
        )

    # Step 2: Missing or whitespace-only job description -> 422 (Requirement 1.6).
    if job_description is None or job_description.strip() == "":
        raise HTTPException(
            status_code=422,
            detail="A job description is required but was empty or missing.",
        )

    # Step 3: Job description exceeds the maximum length -> 422 (Requirement 1.7).
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                "The job description is too long: it must be at most "
                f"{MAX_JOB_DESCRIPTION_CHARS} characters, but it has "
                f"{len(job_description)} characters."
            ),
        )

    # Step 4: Unsupported content type -> 415 (Requirement 2.2).
    # Validated before reading the bytes to honor the precedence order.
    if resume.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported resume content type "
                f"{resume.content_type!r}. Supported types are: "
                f"{', '.join(SUPPORTED_CONTENT_TYPES)}."
            ),
        )

    # Read the uploaded file bytes exactly once; size and emptiness checks below
    # operate on these bytes.
    data = await resume.read()

    # Step 5: File exceeds the maximum size -> 413 (Requirement 2.4).
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The resume file is too large: the maximum allowed size is 10 MB.",
        )

    # Step 6: Empty file (zero readable bytes) -> 422 (Requirement 2.3).
    if len(data) == 0:
        raise HTTPException(
            status_code=422,
            detail="The resume file is empty: it contains zero readable bytes.",
        )

    # Step 7: Extraction/decode error -> 422 (Requirements 3.5, 3.6).
    # On failure the document is never forwarded to the AI service.
    try:
        resume_text = extract_text(data, resume.content_type)
    except ExtractionError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to extract text from the resume: {exc}",
        ) from exc

    # Steps 8-10: orchestrate the AI call, mapping each typed AI service error to
    # its HTTP status code. AIKeyMissingError (500) is caught before the 502
    # errors because it is a more specific configuration failure.
    try:
        return await analyze_resume(resume_text, job_description, projects or "")
    except AIKeyMissingError as exc:
        # Step 8: API key missing -> 500 (Requirement 4.5).
        raise HTTPException(
            status_code=500,
            detail="The AI provider API key is not configured.",
        ) from exc
    except AICallError as exc:
        # Step 9: AI error or timeout -> 502 (Requirement 4.6).
        raise HTTPException(
            status_code=502,
            detail=f"The AI model call did not complete successfully: {exc}",
        ) from exc
    except AIValidationError as exc:
        # Step 10: AI output fails validation -> 502 (Requirement 5.5).
        raise HTTPException(
            status_code=502,
            detail=f"The AI model returned output that failed validation: {exc}",
        ) from exc
