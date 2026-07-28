"""Tests for the AI service (Requirement 4) of the resume-analyzer-latex spec.

Covers two spec tasks that share this file:

* Task 5.2 / Property 19 - the constructed prompt always references all three
  required fields (pure ``build_prompt``; Hypothesis, >=100 examples).
* Task 5.3 - example/edge tests for ``analyze_resume`` with the provider SDK
  mocked, covering Requirements 4.1, 4.3, 4.4, 4.5, and 4.6.

No real network calls are made: the OpenAI SDK client constructor
(``backend.services.ai_service.AsyncOpenAI``) is replaced with a factory that
records its constructor kwargs and returns a mock client whose
``chat.completions.create`` is an ``AsyncMock``.

There is no ``pytest-asyncio`` plugin available, so the async
``analyze_resume`` coroutine is driven with ``asyncio.run(...)`` inside ordinary
(synchronous) test functions.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.services.ai_service import (
    AI_TIMEOUT_SECONDS,
    AICallError,
    AIKeyMissingError,
    AnalysisResult,
    analyze_resume,
    build_prompt,
)

# A valid structured AI response body used by the happy-path tests.
_VALID_PAYLOAD = {
    "percentage": 80,
    "improvements": ["x"],
    "latex_code": "\\documentclass{article}",
}


# ---------------------------------------------------------------------------
# Test helpers: a mock AsyncOpenAI client + installer that captures ctor kwargs
# ---------------------------------------------------------------------------


def _make_fake_response(content: str) -> MagicMock:
    """Build a fake OpenAI response whose ``.choices[0].message.content`` is set.

    Mirrors the minimal shape the production code reads:
    ``response.choices[0].message.content``.
    """
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _install_openai_mock(
    monkeypatch,
    *,
    content: str | None = None,
    create_side_effect: BaseException | None = None,
) -> dict:
    """Patch ``AsyncOpenAI`` with a factory returning a mock client.

    The returned dict exposes:

    * ``constructor_kwargs`` - the kwargs the production code passed to
      ``AsyncOpenAI(...)`` (populated once the factory is invoked).
    * ``create_mock`` - the ``AsyncMock`` standing in for
      ``client.chat.completions.create``.

    Args:
        content: JSON string returned as the message content on success.
        create_side_effect: If provided, the ``create`` mock raises this instead
            of returning a response (used for the error/timeout cases).
    """
    captured: dict = {"constructor_kwargs": None, "create_mock": None}

    create_mock = AsyncMock()
    if create_side_effect is not None:
        create_mock.side_effect = create_side_effect
    else:
        create_mock.return_value = _make_fake_response(content or "")
    captured["create_mock"] = create_mock

    def factory(*args, **kwargs):
        captured["constructor_kwargs"] = kwargs
        client = MagicMock()
        client.chat.completions.create = create_mock
        return client

    monkeypatch.setattr("backend.services.ai_service.AsyncOpenAI", factory)
    return captured


def _use_openai_provider(monkeypatch, *, api_key: str | None = "sk-test-key") -> None:
    """Select the OpenAI provider via env and (optionally) set its API key."""
    monkeypatch.setenv("AI_PROVIDER", "openai")
    if api_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", api_key)


# ---------------------------------------------------------------------------
# Task 5.2 / Property 19 - prompt references all three required fields
# ---------------------------------------------------------------------------

# Feature: resume-analyzer-latex, Property 19: The constructed prompt always references all three required fields
@settings(max_examples=100)
@given(resume_text=st.text(), job_description=st.text())
def test_property_19_prompt_references_all_three_fields(resume_text, job_description):
    """Validates: Requirements 4.2

    For any resume text and job description, ``build_prompt`` produces a prompt
    that references the match percentage, the improvements list, and the LaTeX
    code. This is a pure function, so no mocking is required.
    """
    prompt = build_prompt(resume_text, job_description).lower()

    assert "percentage" in prompt
    assert "improvements" in prompt
    assert "latex" in prompt


# ---------------------------------------------------------------------------
# Task 5.3 - example/edge tests for analyze_resume (SDK mocked)
# ---------------------------------------------------------------------------


def test_single_sdk_call_includes_resume_and_job_description(monkeypatch):
    """Validates: Requirement 4.1

    A single SDK call is made, the prompt carries the resume text and job
    description, and a valid response is parsed into an ``AnalysisResult``.
    """
    _use_openai_provider(monkeypatch)
    captured = _install_openai_mock(monkeypatch, content=json.dumps(_VALID_PAYLOAD))

    result = asyncio.run(analyze_resume("RESUMETEXT", "JOBDESC"))

    assert isinstance(result, AnalysisResult)
    assert result.percentage == 80

    create_mock = captured["create_mock"]
    create_mock.assert_awaited_once()

    sent_prompt = create_mock.await_args.kwargs["messages"][0]["content"]
    assert "RESUMETEXT" in sent_prompt
    assert "JOBDESC" in sent_prompt


def test_api_key_is_read_from_environment(monkeypatch):
    """Validates: Requirement 4.3

    The API key passed to the SDK constructor comes from the environment, not
    from request data.
    """
    sentinel = "sk-sentinel-env-key-12345"
    _use_openai_provider(monkeypatch, api_key=sentinel)
    captured = _install_openai_mock(monkeypatch, content=json.dumps(_VALID_PAYLOAD))

    asyncio.run(analyze_resume("resume", "job"))

    assert captured["constructor_kwargs"] is not None
    assert captured["constructor_kwargs"]["api_key"] == sentinel


def test_call_uses_60_second_timeout(monkeypatch):
    """Validates: Requirement 4.4

    The AI call applies a 60-second timeout. The implementation passes the
    timeout to both the constructor and the ``create`` call; we assert at least
    the ``create`` kwarg and the module constant.
    """
    _use_openai_provider(monkeypatch)
    captured = _install_openai_mock(monkeypatch, content=json.dumps(_VALID_PAYLOAD))

    asyncio.run(analyze_resume("resume", "job"))

    assert AI_TIMEOUT_SECONDS == 60

    create_mock = captured["create_mock"]
    assert create_mock.await_args.kwargs["timeout"] == 60
    # The constructor is also given the 60s timeout by the implementation.
    assert captured["constructor_kwargs"]["timeout"] == 60


def test_ai_error_raises_ai_call_error(monkeypatch):
    """Validates: Requirement 4.6

    A generic error from the SDK call surfaces as ``AICallError`` (mapped to
    HTTP 502 by the route layer).
    """
    _use_openai_provider(monkeypatch)
    _install_openai_mock(monkeypatch, create_side_effect=Exception("boom"))

    with pytest.raises(AICallError):
        asyncio.run(analyze_resume("resume", "job"))


def test_ai_timeout_raises_ai_call_error(monkeypatch):
    """Validates: Requirement 4.6

    A timeout-like error from the SDK call surfaces as ``AICallError`` (mapped
    to HTTP 502 by the route layer).
    """
    _use_openai_provider(monkeypatch)
    _install_openai_mock(
        monkeypatch, create_side_effect=TimeoutError("request timed out")
    )

    with pytest.raises(AICallError):
        asyncio.run(analyze_resume("resume", "job"))


def test_missing_api_key_raises_key_missing_error(monkeypatch):
    """Validates: Requirement 4.5

    When the OpenAI provider is selected but no key is configured,
    ``analyze_resume`` raises ``AIKeyMissingError`` (mapped to HTTP 500).
    """
    _use_openai_provider(monkeypatch, api_key=None)
    # Install a mock so that, were a call attempted, it still would not hit the
    # network; key resolution should fail before any call is made.
    _install_openai_mock(monkeypatch, content=json.dumps(_VALID_PAYLOAD))

    with pytest.raises(AIKeyMissingError):
        asyncio.run(analyze_resume("resume", "job"))
