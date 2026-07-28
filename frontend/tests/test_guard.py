"""Tests for the frontend submit guard ``should_submit`` (Task 9.2).

Covers Property 18 from the design with a Hypothesis property test plus a few
explicit example unit tests. The module under test is imported directly; doing
so does not launch the Streamlit UI (the UI lives under ``main()`` guarded by
``if __name__ == "__main__"``).

Validates: Requirements 7.4, 7.5, 7.6
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from frontend.app import should_submit


# A resume is either absent (None) or a sentinel non-None object standing in for
# an uploaded file. A whitespace-only strategy is mixed in so the property
# exercises both the "blank job description" and the "real content" branches.
resume_strategy = st.one_of(st.none(), st.builds(object))
job_description_strategy = st.one_of(
    st.text(),
    st.text(alphabet=" \t\n\r"),
)


# Feature: resume-analyzer-latex, Property 18: The frontend submits exactly when inputs are valid
@settings(max_examples=200)
@given(resume=resume_strategy, job_description=job_description_strategy)
def test_property_should_submit_iff_inputs_valid(resume, job_description: str) -> None:
    """``should_submit`` is True iff a resume is present and the job description
    contains at least one non-whitespace character (Req 7.4, 7.5, 7.6)."""
    expected = (resume is not None) and (job_description.strip() != "")
    assert should_submit(resume, job_description) is expected


# --- Explicit example unit tests -------------------------------------------------

def test_no_resume_with_text_does_not_submit() -> None:
    """Missing resume blocks submission even with a valid job description (Req 7.4)."""
    assert should_submit(None, "job") is False


def test_resume_with_whitespace_only_job_description_does_not_submit() -> None:
    """Whitespace-only job description blocks submission (Req 7.5)."""
    assert should_submit(object(), "   ") is False


def test_resume_with_empty_job_description_does_not_submit() -> None:
    """Empty job description blocks submission (Req 7.5)."""
    assert should_submit(object(), "") is False


def test_resume_with_real_job_description_submits() -> None:
    """Both inputs valid -> submission proceeds (Req 7.6)."""
    assert should_submit(object(), "Backend engineer") is True
