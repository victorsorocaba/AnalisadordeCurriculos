"""Streamlit frontend for the resume-analyzer-latex application.

This module renders the user interface (Requirements 7, 8, 9) and talks to the
FastAPI backend over HTTP. It is intentionally structured so that importing the
module has **no** Streamlit side effects: the UI flow lives inside ``main()`` and
is only invoked under the ``if __name__ == "__main__"`` guard (which is how
``streamlit run`` executes a script). The pure, deterministic helpers
(``should_submit``, ``post_analysis``, ``extract_error_message``,
``format_improvements``, ``format_percentage``, ``render_results``) are importable
at module level without launching the UI, so they can be unit- and
property-tested directly (tasks 9.2-9.4).

Configuration:
    ``BACKEND_URL`` is read from the environment (loaded via ``python-dotenv`` in
    development) and defaults to ``http://localhost:8000`` (Requirement 10.3).
"""

from __future__ import annotations

import os

import requests
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from a local .env file in development. This is a
# no-op when no .env file is present, so it is safe to call at import time.
load_dotenv()

# Base URL of the FastAPI backend (Requirement 10.3). Read once at import; the
# pure ``post_analysis`` helper still accepts the URL as an argument so tests can
# override it without touching module state.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# The multipart field name the backend expects for the uploaded resume file
# (matches the ``resume: UploadFile`` parameter in /backend/main.py).
RESUME_FIELD_NAME = "resume"

# --- User-facing messages (kept as constants for consistency and testability) ---
MSG_UPLOAD_RESUME = "Please upload a resume file (PDF or TXT) before analyzing."
MSG_ENTER_JOB_DESCRIPTION = "Please enter a job description before analyzing."
MSG_NO_IMPROVEMENTS = "No improvements were suggested."
MSG_GENERIC_ERROR = (
    "The analysis could not be completed. Please try again."
)
MSG_CONNECTION_ERROR = (
    "Could not reach the analysis service. Please check that the backend is "
    "running and try again."
)
MSG_SPINNER = "Analyzing your resume against the job description..."


def should_submit(resume, job_description: str) -> bool:
    """Return ``True`` only when the analysis request should be sent.

    The guard returns ``True`` if and only if a resume is present (not ``None``)
    **and** the job description contains at least one non-whitespace character
    (Requirements 7.4, 7.5, 7.6). It is pure and has no side effects, so no POST
    is issued when it returns ``False``.

    Args:
        resume: The uploaded resume object (``None`` when nothing is selected).
        job_description: The free-form job description text.

    Returns:
        ``True`` when both inputs are valid, ``False`` otherwise.
    """
    return resume is not None and bool(job_description and job_description.strip())


def post_analysis(
    backend_url: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str | None,
    job_description: str,
    projects: str = "",
) -> requests.Response:
    """POST the resume and job description to the backend analysis endpoint.

    Sends a multipart request containing the resume file part, the
    ``job_description`` form field, and the optional ``projects`` form field to
    ``{backend_url}/api/analyze`` with a 60-second timeout (Requirements 8.1).
    This helper is importable and side effect free aside from the network call,
    so tests can monkeypatch ``requests`` to assert on the request shape.

    Args:
        backend_url: Base URL of the FastAPI backend.
        file_name: The uploaded file's name.
        file_bytes: The raw bytes of the uploaded file.
        content_type: The declared content type of the uploaded file.
        job_description: The job description text field value.
        projects: Optional free-form project text. When non-blank it is sent as
            the ``projects`` form field; when blank it is omitted.

    Returns:
        The :class:`requests.Response` returned by the backend.
    """
    url = f"{backend_url.rstrip('/')}/api/analyze"
    files = {RESUME_FIELD_NAME: (file_name, file_bytes, content_type)}
    data = {"job_description": job_description}
    if projects and projects.strip():
        data["projects"] = projects
    return requests.post(url, files=files, data=data, timeout=60)


def extract_error_message(response: requests.Response) -> str:
    """Extract a human-readable error message from a non-success response.

    Reads the ``detail`` field from the response JSON body (FastAPI's default
    error shape) and returns it. Falls back to a generic message when the body
    is not JSON, is not an object, or carries no ``detail`` (Requirement 8.4).

    Args:
        response: The backend response with a non-success status.

    Returns:
        The backend-provided ``detail`` message, or a generic fallback.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        return MSG_GENERIC_ERROR

    if isinstance(body, dict):
        detail = body.get("detail")
        if detail:
            return detail if isinstance(detail, str) else str(detail)

    return MSG_GENERIC_ERROR


def format_improvements(improvements: list[str]) -> list[str]:
    """Format the improvements list into ordered display strings.

    Returns one display string per improvement, prefixed with its 1-based
    position (e.g. ``"1. ..."``), **preserving the original order**
    (Requirement 9.2). Pure and deterministic; an empty input yields an empty
    list.

    Args:
        improvements: The improvement strings received from the backend.

    Returns:
        Ordered list of display strings, one per improvement.
    """
    return [f"{index}. {item}" for index, item in enumerate(improvements, start=1)]


def format_percentage(percentage) -> str:
    """Format the match percentage with a trailing percent indicator.

    Produces the value displayed by the metric component, e.g. ``"87%"``
    (Requirement 9.1).

    Args:
        percentage: The integer match percentage (0-100).

    Returns:
        The percentage as a string with a trailing ``%``.
    """
    return f"{percentage}%"


def render_results(result: dict) -> None:
    """Render an analysis result to the Streamlit UI (Requirements 9.1-9.4).

    - Renders the match percentage via ``st.metric`` with a ``%`` indicator.
    - Renders each improvement as a separate, individually visible ordered list
      item preserving order, or a "no improvements" message when the list is
      empty.
    - Renders the LaTeX code verbatim in ``st.code`` (with its built-in
      copy-to-clipboard control).

    The ``latex_code`` string is passed to ``st.code`` byte-for-byte unmodified.

    Args:
        result: The parsed success body with ``percentage``, ``improvements``,
            and ``latex_code`` keys.
    """
    percentage = result.get("percentage")
    improvements = result.get("improvements", [])
    latex_code = result.get("latex_code", "")

    # Match percentage as a metric with a % unit indicator (Req 9.1).
    st.metric(label="Match Percentage", value=format_percentage(percentage))

    # Improvements: each item individually visible, in order (Req 9.2); or a
    # "no improvements" message when the list is empty (Req 9.3).
    st.subheader("Suggested Improvements")
    if improvements:
        for line in format_improvements(improvements):
            st.markdown(line)
    else:
        st.info(MSG_NO_IMPROVEMENTS)

    # LaTeX code rendered verbatim with a copy control (Req 9.4).
    st.subheader("Generated LaTeX Resume")
    st.code(latex_code, language="latex")


def main() -> None:
    """Render the full Streamlit UI and drive the request/response flow.

    This function contains all Streamlit side effects. It is only invoked under
    the ``if __name__ == "__main__"`` guard so that importing this module (e.g.
    in tests) does not launch any UI.
    """
    st.set_page_config(page_title="Resume Analyzer + LaTeX Generator", page_icon="📄")
    st.title("Resume Analyzer + LaTeX Generator")
    st.write(
        "Upload your resume and paste a job description to get a suitability "
        "score, targeted improvements, and a compilation-ready LaTeX resume."
    )

    # Input components (Requirements 7.1-7.3).
    resume = st.file_uploader(
        "Upload your resume (PDF or TXT)", type=["pdf", "txt"]
    )
    job_description = st.text_area(
        "Job description", height=240, placeholder="Paste the job description here..."
    )
    projects = st.text_area(
        "Projects (optional)",
        height=160,
        placeholder=(
            "Describe your projects here, one per line. Leave blank to skip the "
            "Projetos section entirely."
        ),
        help=(
            "If you add content here, the AI formats it into a Projetos section. "
            "If left blank, no Projetos section is created."
        ),
    )
    submit = st.button("Analyze", type="primary")

    if not submit:
        return

    # Submit guard (Requirements 7.4-7.6): do not POST when inputs are invalid.
    if not should_submit(resume, job_description):
        if resume is None:
            st.warning(MSG_UPLOAD_RESUME)
        if not (job_description and job_description.strip()):
            st.warning(MSG_ENTER_JOB_DESCRIPTION)
        return

    # Valid submit: POST inside a spinner so it always hides on completion,
    # whether the call succeeds, returns an error status, or raises
    # (Requirements 8.1-8.3).
    try:
        with st.spinner(MSG_SPINNER):
            response = post_analysis(
                BACKEND_URL,
                resume.name,
                resume.getvalue(),
                resume.type,
                job_description,
                projects,
            )
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
    ):
        # Transport failure: connection error / timeout / no response (Req 8.5).
        st.error(MSG_CONNECTION_ERROR)
        return

    # Non-success response: show the backend's detail or a generic fallback
    # (Requirement 8.4).
    if response.status_code >= 400:
        st.error(extract_error_message(response))
        return

    # Success: parse and render the analysis result (Requirements 9.1-9.4).
    try:
        result = response.json()
    except ValueError:
        st.error(MSG_GENERIC_ERROR)
        return

    render_results(result)


if __name__ == "__main__":
    main()
