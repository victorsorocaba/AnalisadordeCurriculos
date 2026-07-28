"""Pydantic input and output schemas for the resume-analyzer-latex backend.

This module defines the request and response contracts for the analysis
endpoint (Requirement 6). The output model doubles as the strict validator for
the AI model's structured output (Requirement 5): it enforces exactly three
fields with precise types so malformed analysis data is never returned to the
frontend.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class AnalyzeInput(BaseModel):
    """Input model for the job description text field (Requirements 6.1, 6.2).

    The resume file part is handled by FastAPI's ``UploadFile`` (binary) rather
    than a Pydantic field, which is the idiomatic FastAPI pattern for multipart
    uploads. The job description is capped at 20,000 characters (Requirement
    1.2 / 1.7).
    """

    job_description: str = Field(..., max_length=20_000)


class AnalysisResult(BaseModel):
    """Structured analysis output (Requirements 5, 6.1, 6.3, 6.4, 6.5).

    Serializes to a JSON object containing exactly the three fields
    ``percentage``, ``improvements``, and ``latex_code`` and no additional
    fields (``extra="forbid"``, Requirement 6.4).
    """

    model_config = ConfigDict(extra="forbid")  # exactly three fields (Req 6.4)

    # Strict integer in the inclusive range [0, 100]: floats such as 95.0 and
    # string values are rejected (Requirements 5.2, 6.5).
    percentage: Annotated[int, Field(ge=0, le=100, strict=True)]

    # List of strings; the empty list is allowed (Requirements 5.3, 6.5).
    improvements: list[str]

    # Non-empty string (Requirements 5.4, 6.5).
    latex_code: Annotated[str, Field(min_length=1)]


def strip_markdown_fences(text: str) -> str:
    """Remove a wrapping triple-backtick markdown fence from ``text`` (Req 5.6).

    AI models frequently wrap generated code in markdown fences such as::

        ```latex
        \\documentclass{article}
        ...
        ```

    even when instructed not to. This pure, deterministic helper normalizes that
    output so the stored ``latex_code`` is compilation-ready.

    Behavior:

    - The input is first stripped of surrounding whitespace.
    - If the trimmed text is wrapped in a triple-backtick fence -- an opening
      line that begins with ```` ``` ```` and may carry an optional language
      token (e.g. ``latex``) directly after the backticks, together with a
      matching closing line that is exactly ```` ``` ```` -- both fences and the
      language token are removed and the inner content is returned with its own
      leading/trailing whitespace stripped.
    - Otherwise the whitespace-trimmed input is returned unchanged.

    The function performs no I/O, is deterministic, and is idempotent for
    unfenced strings (applying it twice yields the same result as applying it
    once).

    Args:
        text: The raw string that may or may not be wrapped in a markdown fence.

    Returns:
        The unfenced, whitespace-trimmed content.
    """
    stripped = text.strip()

    # A wrapping fence needs at least an opening line and a closing line.
    lines = stripped.split("\n")
    if len(lines) < 2:
        return stripped

    # Opening fence: the first line must start with three backticks. Any
    # remaining text on that line is treated as the optional language token and
    # discarded. Leading whitespace was already removed by ``strip`` above.
    if not lines[0].startswith("```"):
        return stripped

    # Closing fence: the last line, ignoring surrounding whitespace, must be
    # exactly three backticks for the text to count as fully wrapped.
    if lines[-1].strip() != "```":
        return stripped

    # Drop the opening and closing fence lines, then trim the inner content.
    inner = "\n".join(lines[1:-1])
    return inner.strip()
