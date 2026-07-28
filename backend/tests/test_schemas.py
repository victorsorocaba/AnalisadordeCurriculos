"""Tests for the Pydantic schemas and LaTeX-cleaning helper.

Covers spec tasks 2.3-2.12 for the ``resume-analyzer-latex`` feature:

* Property-based tests (Hypothesis) for Properties 1-6, each running at least
  100 examples and tagged with a ``# Feature: resume-analyzer-latex, Property N``
  comment.
* Explicit Requirement 11 unit tests (tasks 2.9-2.12).

The module under test (``backend/models/schemas.py``) is treated as correct;
these tests only exercise its documented behavior.
"""

import json

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.models.schemas import AnalysisResult, AnalyzeInput, strip_markdown_fences


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Inner content for fenced strings: non-empty, no backticks (so it can never
# accidentally form a fence) and no carriage returns (the helper splits on
# "\n" only). Surrogate code points are excluded to keep values encodable.
_SAFE_INNER = st.text(
    alphabet=st.characters(blacklist_characters="`\r", blacklist_categories=("Cs",)),
    min_size=1,
)

# Optional markdown language token on the opening fence (e.g. ``latex``).
_LANGUAGE_TOKEN = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    max_size=12,
)

# Valid building blocks for AnalysisResult.
_VALID_PERCENTAGE = st.integers(min_value=0, max_value=100)
_VALID_IMPROVEMENTS = st.lists(st.text())
_VALID_LATEX = st.text(min_size=1)

# Non-string values that Pydantic does NOT coerce into a str (bytes is omitted
# on purpose because lax mode decodes it into a str).
_NON_STRING = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.none(),
    st.booleans(),
)


def _looks_fenced(text: str) -> bool:
    """Replicate the helper's wrapping-fence detection for a trimmed string."""
    stripped = text.strip()
    lines = stripped.split("\n")
    return (
        len(lines) >= 2
        and lines[0].startswith("```")
        and lines[-1].strip() == "```"
    )


@st.composite
def _improvements_with_non_string(draw):
    """A list of strings into which at least one non-string element is spliced."""
    base = draw(st.lists(st.text()))
    bad = draw(_NON_STRING)
    index = draw(st.integers(min_value=0, max_value=len(base)))
    base.insert(index, bad)
    return base


# ---------------------------------------------------------------------------
# Property 1 (task 2.3)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 1: Markdown fence stripping is correct and idempotent
@settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
@given(inner=_SAFE_INNER, language=_LANGUAGE_TOKEN)
def test_property_1_fenced_strings_round_trip(inner, language):
    """Validates: Requirements 5.6.

    Wrapping a non-empty inner string in triple-backtick fences (with an
    optional language id) and stripping it yields the inner string trimmed.
    """
    wrapped = f"```{language}\n{inner}\n```"
    assert strip_markdown_fences(wrapped) == inner.strip()


# Feature: resume-analyzer-latex, Property 1: Markdown fence stripping is correct and idempotent
@settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
@given(text=st.text())
def test_property_1_unfenced_strings_are_trimmed_and_idempotent(text):
    """Validates: Requirements 5.6.

    For an already-unfenced string, stripping returns the trimmed input and
    applying the helper twice equals applying it once.
    """
    assume(not _looks_fenced(text))
    once = strip_markdown_fences(text)
    assert once == text.strip()
    assert strip_markdown_fences(once) == once


# ---------------------------------------------------------------------------
# Property 2 (task 2.4)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 2: Output schema round-trips with exactly three fields and correct types
@settings(max_examples=100)
@given(
    percentage=_VALID_PERCENTAGE,
    improvements=_VALID_IMPROVEMENTS,
    latex_code=_VALID_LATEX,
)
def test_property_2_output_schema_round_trips(percentage, improvements, latex_code):
    """Validates: Requirements 6.4, 6.5, 6.3.

    JSON serialization round-trips to an equal object, and the serialized
    object has exactly the three required keys with the correct types.
    """
    model = AnalysisResult(
        percentage=percentage, improvements=improvements, latex_code=latex_code
    )

    restored = AnalysisResult.model_validate_json(model.model_dump_json())
    assert restored == model

    serialized = json.loads(model.model_dump_json())
    assert set(serialized.keys()) == {"percentage", "improvements", "latex_code"}
    assert isinstance(serialized["percentage"], int) and not isinstance(
        serialized["percentage"], bool
    )
    assert isinstance(serialized["improvements"], list)
    assert all(isinstance(item, str) for item in serialized["improvements"])
    assert isinstance(serialized["latex_code"], str)


# ---------------------------------------------------------------------------
# Property 3 (task 2.5)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 3: Percentage is accepted exactly when it is an integer in [0, 100]
@settings(max_examples=200)
@given(
    candidate=st.one_of(
        st.integers(),
        st.integers(min_value=0, max_value=100),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(),
        st.booleans(),
    )
)
def test_property_3_percentage_accepted_iff_int_in_range(candidate):
    """Validates: Requirements 5.2.

    The percentage is accepted if and only if it is a strict integer (bool is
    rejected) within the inclusive range [0, 100].
    """
    # bool is a subclass of int, so ``type(...) is int`` excludes True/False.
    should_accept = type(candidate) is int and 0 <= candidate <= 100

    if should_accept:
        result = AnalysisResult(
            percentage=candidate, improvements=[], latex_code="x"
        )
        assert result.percentage == candidate
    else:
        with pytest.raises(ValidationError):
            AnalysisResult(percentage=candidate, improvements=[], latex_code="x")


# ---------------------------------------------------------------------------
# Property 4 (task 2.6)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 4: Improvements is accepted exactly when it is a list of strings
@settings(max_examples=150)
@given(
    candidate=st.one_of(
        st.lists(st.text()),
        _improvements_with_non_string(),
    )
)
def test_property_4_improvements_accepted_iff_list_of_strings(candidate):
    """Validates: Requirements 5.3.

    A list is accepted (including the empty list) if and only if every element
    is a string; any non-string element fails validation.
    """
    should_accept = all(isinstance(item, str) for item in candidate)

    if should_accept:
        result = AnalysisResult(
            percentage=50, improvements=candidate, latex_code="x"
        )
        assert result.improvements == candidate
    else:
        with pytest.raises(ValidationError):
            AnalysisResult(percentage=50, improvements=candidate, latex_code="x")


# ---------------------------------------------------------------------------
# Property 5 (task 2.7)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 5: LaTeX code is accepted exactly when it is a non-empty string
@settings(max_examples=150)
@given(
    candidate=st.one_of(
        st.text(min_size=1),
        st.just(""),
        _NON_STRING,
    )
)
def test_property_5_latex_accepted_iff_non_empty_string(candidate):
    """Validates: Requirements 5.4.

    LaTeX code is accepted if and only if it is a string with at least one
    character; an empty string or a non-string value fails validation.
    """
    should_accept = isinstance(candidate, str) and len(candidate) >= 1

    if should_accept:
        result = AnalysisResult(
            percentage=50, improvements=[], latex_code=candidate
        )
        assert result.latex_code == candidate
    else:
        with pytest.raises(ValidationError):
            AnalysisResult(percentage=50, improvements=[], latex_code=candidate)


# ---------------------------------------------------------------------------
# Property 6 (task 2.8)
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 6: Missing any required field fails validation
@settings(max_examples=100)
@given(
    percentage=_VALID_PERCENTAGE,
    improvements=_VALID_IMPROVEMENTS,
    latex_code=_VALID_LATEX,
    omitted=st.sampled_from(["percentage", "improvements", "latex_code"]),
)
def test_property_6_missing_required_field_fails(
    percentage, improvements, latex_code, omitted
):
    """Validates: Requirements 5.1.

    Removing any one of the three required fields from an otherwise-valid
    object causes validation to fail.
    """
    valid = {
        "percentage": percentage,
        "improvements": improvements,
        "latex_code": latex_code,
    }
    del valid[omitted]

    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(valid)


# ---------------------------------------------------------------------------
# Unit tests (Requirement 11)
# ---------------------------------------------------------------------------


def test_conforming_ai_output_validates_without_error():
    """Task 2.9 / Requirement 11.3: conforming AI output validates cleanly."""
    result = AnalysisResult(
        percentage=82,
        improvements=["Quantify your achievements", "Tailor the summary"],
        latex_code="\\documentclass{article}\\begin{document}Hi\\end{document}",
    )

    assert result.percentage == 82
    assert result.improvements == [
        "Quantify your achievements",
        "Tailor the summary",
    ]
    assert result.latex_code.startswith("\\documentclass")


def test_out_of_range_percentage_rejected():
    """Task 2.10 / Requirement 11.4: percentage below 0 or above 100 fails."""
    with pytest.raises(ValidationError):
        AnalysisResult(percentage=-1, improvements=[], latex_code="x")

    with pytest.raises(ValidationError):
        AnalysisResult(percentage=101, improvements=[], latex_code="x")


@pytest.mark.parametrize("missing", ["percentage", "improvements", "latex_code"])
def test_missing_field_rejected(missing):
    """Task 2.11 / Requirement 11.5: missing any required field fails."""
    valid = {
        "percentage": 50,
        "improvements": ["Add a skills section"],
        "latex_code": "\\documentclass{article}",
    }
    del valid[missing]

    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(valid)


@pytest.mark.parametrize("boundary", [0, 100])
def test_boundary_percentages_accepted(boundary):
    """Task 2.12 / Requirement 11.6: boundary percentages 0 and 100 validate."""
    result = AnalysisResult(
        percentage=boundary, improvements=[], latex_code="\\documentclass{article}"
    )
    assert result.percentage == boundary


def test_analyze_input_accepts_job_description():
    """Sanity check that the imported input model is usable."""
    model = AnalyzeInput(job_description="Senior Python engineer")
    assert model.job_description == "Senior Python engineer"
