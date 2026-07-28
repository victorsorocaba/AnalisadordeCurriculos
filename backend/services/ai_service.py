"""AI service for the resume-analyzer-latex backend (Requirements 4, 5, 10.2).

This module is the *only* component that talks to an AI provider. It:

- reads the provider selection and API key from environment configuration,
  never from request data (Requirements 4.3, 4.5);
- builds a prompt instructing the model to return exactly the three required
  fields -- the match percentage, the improvements list, and the LaTeX code --
  with no markdown fences and no surrounding prose (Requirement 4.2);
- makes a *single* direct SDK call with an explicit 60-second timeout, using the
  OpenAI SDK by default and the Google GenAI SDK as an alternative
  (Requirements 4.1, 4.4);
- cleans the returned ``latex_code`` with :func:`strip_markdown_fences` and
  validates the whole structured result against :class:`AnalysisResult`
  (Requirements 5.5, 5.6).

The provider SDKs are imported only here so the rest of the backend stays
provider-agnostic. All failure modes are surfaced as the typed exceptions below,
which ``main.py`` maps to the appropriate HTTP status codes.
"""

from __future__ import annotations

import json
import os

from openai import AsyncOpenAI
from google import genai
from google.genai import types as genai_types
from pydantic import ValidationError

from backend.models.schemas import AnalysisResult, strip_markdown_fences

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

#: Per-request timeout applied to the AI model call (Requirement 4.4).
AI_TIMEOUT_SECONDS = 60

#: The Google GenAI SDK expresses request timeouts in milliseconds.
_AI_TIMEOUT_MILLISECONDS = AI_TIMEOUT_SECONDS * 1000

#: Default model identifiers per provider, used when ``AI_MODEL`` is unset.
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_GOOGLE_MODEL = "gemini-2.0-flash"

_OPENAI_PROVIDER = "openai"
_GOOGLE_PROVIDER = "google"


# ---------------------------------------------------------------------------
# Typed error hierarchy (mapped to HTTP status codes by main.py)
# ---------------------------------------------------------------------------


class AIServiceError(Exception):
    """Base class for all AI service failures."""


class AIKeyMissingError(AIServiceError):
    """The provider API key is absent from environment configuration.

    Mapped to HTTP 500 by ``main.py`` (Requirement 4.5).
    """


class AICallError(AIServiceError):
    """The AI model call raised an error or exceeded the 60-second timeout.

    Mapped to HTTP 502 by ``main.py`` (Requirements 4.1, 4.4, 4.6).
    """


class AIValidationError(AIServiceError):
    """The AI model output could not be parsed or failed schema validation.

    Mapped to HTTP 502 by ``main.py`` (Requirements 5.5, 5.6).
    """


# ---------------------------------------------------------------------------
# Prompt construction (pure, importable)
# ---------------------------------------------------------------------------


def build_prompt(
    resume_text: str, job_description: str, projects: str = ""
) -> str:
    """Build the AI prompt for a resume/job-description analysis (Req 4.2).

    The returned prompt is a pure function of its inputs (no I/O, deterministic)
    and always references all three required output fields: the match
    **percentage**, the list of **improvements**, and the **LaTeX** code. It
    instructs the model to respond with a single JSON object containing exactly
    those fields, with no markdown code fences and no surrounding prose. The
    prompt also constrains the generated ``latex_code`` to be ATS-friendly
    (single column, no tables/graphics, machine-extractable text, classic
    section titles) and applies content-rewriting guidelines (keyword-focused
    summary, measurable impact in experience, contextualized soft skills and
    languages).

    The Projetos section is optional and driven by ``projects``: when the
    candidate provides project text, the model formats it into a
    ``\\section*{Projetos}``; when ``projects`` is empty/blank, the model must
    NOT create a Projetos section at all.

    Args:
        resume_text: The extracted plain text of the candidate's resume.
        job_description: The target job description supplied by the user.
        projects: Optional free-form text describing the candidate's projects.
            When blank, no Projetos section is generated.

    Returns:
        The complete prompt string to send to the AI model.
    """
    projects_clean = projects.strip()
    if projects_clean:
        projects_rule = (
            "  - Projects section: the candidate provided project information "
            "(see the PROJECTS block below). Create a \\section*{Projetos} "
            "section and format the provided projects into it using itemize, "
            "rewriting them for clarity and impact. Use ONLY the information in "
            "the PROJECTS block and the resume; do NOT fabricate or invent "
            "projects, technologies, or achievements that are not present "
            "there.\n"
        )
        projects_block = f"\n=== PROJECTS ===\n{projects_clean}\n"
    else:
        projects_rule = (
            "  - Projects section: the candidate provided NO project "
            "information. Do NOT create a \\section*{Projetos} section and do "
            "NOT invent any projects.\n"
        )
        projects_block = ""
    return (
        "You are a resume analysis assistant. Compare the resume below against "
        "the target job description and produce a suitability analysis.\n\n"
        "Return your answer as a single JSON object with EXACTLY these three "
        "fields and no others:\n"
        '  - "percentage": an integer from 0 to 100 (inclusive) representing '
        "the match percentage between the resume and the job description.\n"
        '  - "improvements": a list of strings, each a short, objective, direct '
        "improvement the candidate should make to the resume. The list may be "
        "empty if no improvements are needed.\n"
        '  - "latex_code": a string containing complete, compilation-ready '
        "LaTeX source for an improved version of the resume.\n\n"
        "ATS optimization requirements (the latex_code MUST follow ALL of "
        "these so the resulting PDF is reliably parsed by Applicant Tracking "
        "Systems):\n"
        "  - Linear structure: produce a SINGLE-COLUMN document with a direct "
        "top-to-bottom reading flow. The content order must read sequentially "
        "from top to bottom.\n"
        "  - No complex visual elements: do NOT use tables, tabular, minipage, "
        "multiple columns (no multicol, no two-column layouts), text boxes, "
        "icons, images, graphics packages (e.g. tikz, graphicx), colored "
        "backgrounds, or any element that breaks linear text extraction.\n"
        "  - Machine-readable typography: use only simple, standard formatting "
        "(e.g. \\section, \\subsection, itemize, \\textbf) and a standard font "
        "so that ALL text in the resulting PDF is perfectly selectable and "
        "extractable as plain text. Do not render any information as an image "
        "or as decorative glyphs.\n"
        "  - Classic section titles: use standardized section names that "
        "recruitment robots expect. Prefer, in the resume's language, the "
        "equivalents of: Professional Summary (Resumo Profissional), "
        "Experience (Experiencia), Education (Educacao), and Skills "
        "(Habilidades).\n\n"
        "Content rewriting guidelines (apply these when generating the improved "
        "latex_code and when listing improvements):\n"
        "  - Professional summary: rewrite it to be short, direct, and focused "
        "on the keywords from the job description. Remove generic, filler, or "
        "overly flowery wording.\n"
        "  - Measurable impact in experience: for each real experience found in "
        "the resume, rewrite the bullet points to add impact context where it "
        "is supported by the candidate's information (e.g. performance "
        "improvement, system stability, cost reduction). Do NOT invent numbers "
        "or outcomes that are not implied by the resume; when a concrete metric "
        "is missing, phrase the impact qualitatively and add an improvement "
        "suggesting the candidate quantify it.\n"
        "  - Soft skills and languages: do NOT list soft skills as bare, "
        "free-floating words. Describe each soft skill within a practical "
        "context tied to the candidate's experience. For language proficiency, "
        "especially English, specify the practical usage (e.g. reading "
        "technical documentation) rather than a vague level label.\n"
        f"{projects_rule}"
        "  - ATS layout reinforcement: the generated LaTeX must NOT use complex "
        "or multi-column layouts; rely on \\section* and itemize so the result "
        "is compatible with ATS platforms such as Gupy and Greenhouse.\n\n"
        "Formatting rules:\n"
        "  - Respond with ONLY the raw JSON object.\n"
        "  - Do NOT wrap the response or the latex_code in markdown code "
        "fences (no triple backticks) and do NOT add any surrounding prose.\n"
        "  - The latex_code value must be plain LaTeX, not wrapped in markdown.\n\n"
        "=== RESUME TEXT ===\n"
        f"{resume_text}\n\n"
        "=== JOB DESCRIPTION ===\n"
        f"{job_description}\n"
        f"{projects_block}"
    )


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------


def _resolve_provider() -> str:
    """Return the configured provider (``openai`` default, or ``google``)."""
    provider = (os.getenv("AI_PROVIDER") or _OPENAI_PROVIDER).strip().lower()
    return provider or _OPENAI_PROVIDER


def _resolve_api_key(provider: str) -> str:
    """Read the provider API key from the environment (Requirements 4.3, 4.5).

    The key is read exclusively from environment configuration, never from
    request data.

    Raises:
        AIKeyMissingError: If the relevant key is absent or empty.
    """
    if provider == _OPENAI_PROVIDER:
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
    elif provider == _GOOGLE_PROVIDER:
        key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    else:
        raise AIServiceError(f"Unsupported AI provider: {provider!r}")

    if not key:
        raise AIKeyMissingError(
            "The AI provider API key is not configured. Set the "
            f"{'OPENAI_API_KEY' if provider == _OPENAI_PROVIDER else 'GOOGLE_API_KEY'} "
            "environment variable."
        )
    return key


def _resolve_model(provider: str) -> str:
    """Return the model id, honoring an optional ``AI_MODEL`` override."""
    override = (os.getenv("AI_MODEL") or "").strip()
    if override:
        return override
    return _DEFAULT_OPENAI_MODEL if provider == _OPENAI_PROVIDER else _DEFAULT_GOOGLE_MODEL


# ---------------------------------------------------------------------------
# Provider SDK calls (single call each, explicit 60s timeout)
# ---------------------------------------------------------------------------


async def _call_openai(prompt: str, model: str, api_key: str) -> str:
    """Make a single OpenAI chat completion call and return the raw content.

    Uses JSON output mode and an explicit per-request 60-second timeout
    (Requirements 4.1, 4.4). Returns the raw message content for downstream
    JSON parsing and validation.
    """
    client = AsyncOpenAI(api_key=api_key, timeout=AI_TIMEOUT_SECONDS)
    response = await client.chat.completions.create(
        model=model,
        timeout=AI_TIMEOUT_SECONDS,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


async def _call_google(prompt: str, model: str, api_key: str) -> str:
    """Make a single Google GenAI call and return the raw text content.

    Requests a JSON response and applies an explicit 60-second timeout
    (expressed in milliseconds for the Google SDK) (Requirements 4.1, 4.4).
    """
    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            http_options=genai_types.HttpOptions(timeout=_AI_TIMEOUT_MILLISECONDS),
        ),
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Output parsing and validation
# ---------------------------------------------------------------------------


def _parse_and_validate(raw: str) -> AnalysisResult:
    """Parse ``raw`` as JSON, clean the LaTeX, and validate the result.

    Runs :func:`strip_markdown_fences` on the returned ``latex_code`` value
    (Requirement 5.6), then validates the whole object against
    :class:`AnalysisResult` (Requirement 5.5).

    Raises:
        AIValidationError: If the content is not valid JSON, is not a JSON
            object, or fails Pydantic validation.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AIValidationError(f"AI model output was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AIValidationError("AI model output was not a JSON object.")

    # Clean markdown fences from the LaTeX before strict validation (Req 5.6).
    latex = data.get("latex_code")
    if isinstance(latex, str):
        data["latex_code"] = strip_markdown_fences(latex)

    try:
        return AnalysisResult(**data)
    except (ValidationError, TypeError) as exc:
        raise AIValidationError(
            f"AI model output failed schema validation: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def analyze_resume(
    resume_text: str, job_description: str, projects: str = ""
) -> AnalysisResult:
    """Analyze a resume against a job description via a single AI SDK call.

    Reads the provider and API key from the environment, builds the prompt,
    makes one direct SDK call with a 60-second timeout, then cleans and
    validates the structured output.

    Args:
        resume_text: The extracted plain text of the resume.
        job_description: The target job description.
        projects: Optional free-form project text. When provided, the model is
            asked to format it into a ``\\section*{Projetos}``; when blank, no
            Projetos section is generated.

    Returns:
        A validated :class:`AnalysisResult`.

    Raises:
        AIKeyMissingError: The provider API key is not configured (-> HTTP 500).
        AICallError: The SDK call errored or timed out (-> HTTP 502).
        AIValidationError: The output was unparsable or schema-invalid
            (-> HTTP 502).
    """
    provider = _resolve_provider()
    api_key = _resolve_api_key(provider)
    model = _resolve_model(provider)
    prompt = build_prompt(resume_text, job_description, projects)

    try:
        if provider == _OPENAI_PROVIDER:
            raw = await _call_openai(prompt, model, api_key)
        else:
            raw = await _call_google(prompt, model, api_key)
    except AIServiceError:
        # Configuration errors raised before/around the call propagate as-is.
        raise
    except Exception as exc:  # noqa: BLE001 - any SDK error/timeout -> 502
        raise AICallError(
            f"The AI model call did not complete successfully: {exc}"
        ) from exc

    return _parse_and_validate(raw)
