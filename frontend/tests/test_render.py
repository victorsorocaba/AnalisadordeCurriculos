"""Tests for the Streamlit frontend rendering and request flow.

Covers spec tasks 9.3 and 9.4 for the ``resume-analyzer-latex`` feature:

* Task 9.3 - a property-based test (Hypothesis, >=100 examples) for Property 20,
  asserting that results rendering preserves the order/content of the
  improvements list and passes the LaTeX code to ``st.code`` byte-for-byte.
* Task 9.4 - example/edge tests covering Requirements 7.1-7.3, 8.1, 8.2, 8.3,
  8.4, 8.5, 9.1, and 9.3.

The module under test (``frontend/app.py``) is treated as correct and is never
modified. Streamlit is never actually run: every ``st.*`` function the code
touches is monkeypatched with a recorder, and ``requests``/``post_analysis`` are
monkeypatched so no real network call is ever made.
"""

import requests
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pytest

import frontend.app as app


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class Recorder:
    """A callable that records every call and returns a fixed value.

    Each recorded call is stored as an ``(args, kwargs)`` tuple in ``calls`` so
    tests can assert on exactly what the production code passed to a given
    ``st.*`` function.
    """

    def __init__(self, return_value=None):
        self.calls = []
        self.return_value = return_value

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value


class SpinnerRecorder:
    """A context-manager double for ``st.spinner`` recording enter/exit.

    Calling it (``st.spinner(msg)``) records the call and returns ``self`` so it
    can be used in a ``with`` block. ``__enter__``/``__exit__`` increment
    counters so a test can assert the spinner was both shown and hidden. It does
    not suppress exceptions, mirroring a real context manager.
    """

    def __init__(self):
        self.calls = []
        self.entered = 0
        self.exited = 0

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        return False  # never swallow exceptions


class FakeUploadedFile:
    """Minimal stand-in for a Streamlit ``UploadedFile``.

    Exposes the ``.name``, ``.type`` and ``.getvalue()`` members that
    ``app.main`` reads when building the POST request.
    """

    def __init__(self, name, content_type, data):
        self.name = name
        self.type = content_type
        self._data = data

    def getvalue(self):
        return self._data


class FakeResponse:
    """Minimal stand-in for ``requests.Response``.

    ``status_code`` drives the success/error branch in ``app.main``; ``json()``
    returns ``json_data`` or raises ``json_exc`` to model malformed bodies.
    """

    def __init__(self, status_code=200, json_data=None, json_exc=None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


# Names of every ``st.*`` function ``app`` may call. Patching all of them keeps
# any test that drives ``app.main`` from touching a real Streamlit runtime.
_ST_VOID_FUNCTIONS = (
    "set_page_config",
    "title",
    "write",
    "warning",
    "error",
    "info",
    "metric",
    "markdown",
    "subheader",
    "code",
)


def _patch_st(monkeypatch, *, file_uploader=None, text_area="", button=False, spinner=None):
    """Replace every ``st.*`` function ``app`` uses with a recorder.

    Void/output functions default to no-op recorders. Input widgets return the
    provided defaults (``file_uploader`` -> ``None``, ``text_area`` -> ``""``,
    ``button`` -> ``False``) so ``app.main`` can be driven deterministically.
    ``st.spinner`` is replaced with a :class:`SpinnerRecorder` (or the supplied
    one).

    Returns a dict mapping each ``st`` function name to its recorder so tests can
    assert on the recorded calls.
    """
    recorders = {}

    for name in _ST_VOID_FUNCTIONS:
        rec = Recorder()
        recorders[name] = rec
        monkeypatch.setattr(app.st, name, rec)

    uploader_rec = Recorder(return_value=file_uploader)
    recorders["file_uploader"] = uploader_rec
    monkeypatch.setattr(app.st, "file_uploader", uploader_rec)

    text_area_rec = Recorder(return_value=text_area)
    recorders["text_area"] = text_area_rec
    monkeypatch.setattr(app.st, "text_area", text_area_rec)

    button_rec = Recorder(return_value=button)
    recorders["button"] = button_rec
    monkeypatch.setattr(app.st, "button", button_rec)

    spinner_rec = spinner if spinner is not None else SpinnerRecorder()
    recorders["spinner"] = spinner_rec
    monkeypatch.setattr(app.st, "spinner", spinner_rec)

    return recorders


def _markdown_lines(recorder):
    """Extract the first positional arg from each recorded ``st.markdown`` call."""
    return [args[0] for args, _ in recorder.calls]


# ===========================================================================
# Task 9.3 - Property 20: Results rendering preserves order and content
# ===========================================================================

# Feature: resume-analyzer-latex, Property 20: Results rendering preserves order and content
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    improvements=st.lists(st.text(), min_size=1),
    latex=st.text(min_size=1),
)
def test_property_20_rendering_preserves_order_and_content(
    monkeypatch, improvements, latex
):
    """Validates: Requirements 9.2, 9.4.

    For any non-empty improvements list and any non-empty latex string,
    ``render_results``:
      (a) renders the improvements (captured via ``st.markdown``) in the same
          order and content as the input - equal to ``format_improvements`` of
          the input, which preserves order; and
      (b) passes the latex string to ``st.code`` byte-for-byte unmodified.
    """
    metric = Recorder()
    markdown = Recorder()
    info = Recorder()
    subheader = Recorder()
    code = Recorder()
    monkeypatch.setattr(app.st, "metric", metric)
    monkeypatch.setattr(app.st, "markdown", markdown)
    monkeypatch.setattr(app.st, "info", info)
    monkeypatch.setattr(app.st, "subheader", subheader)
    monkeypatch.setattr(app.st, "code", code)

    app.render_results(
        {"percentage": 50, "improvements": improvements, "latex_code": latex}
    )

    # (a) The rendered improvement lines preserve order and content. The pure
    # formatter is the source of truth and must itself preserve order/content.
    expected_lines = app.format_improvements(improvements)
    assert expected_lines == [
        f"{i}. {item}" for i, item in enumerate(improvements, start=1)
    ]
    rendered_lines = _markdown_lines(markdown)
    assert rendered_lines == expected_lines
    assert len(rendered_lines) == len(improvements)
    for i, item in enumerate(improvements):
        assert rendered_lines[i].endswith(item)

    # A non-empty list never triggers the "no improvements" message.
    assert info.calls == []

    # (b) The latex passed to st.code is byte-for-byte identical to the input.
    assert len(code.calls) == 1
    code_args, code_kwargs = code.calls[0]
    assert code_args[0] == latex
    assert code_args[0] is not None
    assert code_kwargs.get("language") == "latex"


# ===========================================================================
# Task 9.4 - Example / edge tests
# ===========================================================================


# --- Requirements 7.1-7.3: input components are rendered ---


def test_input_components_rendered(monkeypatch):
    """Req 7.1-7.3: file uploader, text area, and button are rendered.

    Driving ``main`` with the button returning ``False`` makes it return right
    after rendering the inputs (no POST), so we can assert the widgets were
    created with the right configuration.
    """
    recorders = _patch_st(monkeypatch, file_uploader=None, text_area="", button=False)

    app.main()

    # File uploader restricted to PDF/TXT (Req 7.1).
    assert len(recorders["file_uploader"].calls) == 1
    _, uploader_kwargs = recorders["file_uploader"].calls[0]
    assert uploader_kwargs.get("type") == ["pdf", "txt"]

    # Multi-line text area for the job description (Req 7.2).
    assert len(recorders["text_area"].calls) == 1

    # Execution button (Req 7.3).
    assert len(recorders["button"].calls) == 1


# --- Requirement 8.1: POST includes file + job description with timeout=60 ---


def test_post_analysis_includes_file_job_description_and_timeout(monkeypatch):
    """Req 8.1: POST hits /api/analyze with the file part, data, and timeout=60."""
    recorder = Recorder(return_value=FakeResponse(status_code=200, json_data={}))
    monkeypatch.setattr(app.requests, "post", recorder)

    app.post_analysis("http://x:8000", "r.txt", b"data", "text/plain", "job")

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    url = args[0] if args else kwargs["url"]
    assert url.endswith("/api/analyze")

    files = kwargs["files"]
    assert app.RESUME_FIELD_NAME in files
    assert files[app.RESUME_FIELD_NAME] == ("r.txt", b"data", "text/plain")

    assert kwargs["data"] == {"job_description": "job"}
    assert kwargs["timeout"] == 60


def test_post_analysis_strips_trailing_slash_on_backend_url(monkeypatch):
    """Req 8.1: a trailing slash on the backend URL does not double the slash."""
    recorder = Recorder(return_value=FakeResponse(status_code=200, json_data={}))
    monkeypatch.setattr(app.requests, "post", recorder)

    app.post_analysis("http://x:8000/", "r.txt", b"data", "text/plain", "job")

    _, kwargs = recorder.calls[0]
    url = kwargs.get("url") or recorder.calls[0][0][0]
    assert url == "http://x:8000/api/analyze"


# --- Requirements 8.2/8.3: spinner shown then hidden ---


def test_spinner_shown_then_hidden_on_success(monkeypatch):
    """Req 8.2/8.3: the spinner context is entered AND exited around the call."""
    spinner = SpinnerRecorder()
    _patch_st(
        monkeypatch,
        file_uploader=FakeUploadedFile("r.txt", "text/plain", b"data"),
        text_area="a real job description",
        button=True,
        spinner=spinner,
    )

    valid_result = {"percentage": 90, "improvements": ["x"], "latex_code": "\\doc"}
    monkeypatch.setattr(
        app,
        "post_analysis",
        lambda *a, **k: FakeResponse(status_code=200, json_data=valid_result),
    )

    app.main()

    assert spinner.entered == 1
    assert spinner.exited == 1


def test_spinner_hidden_even_when_transport_fails(monkeypatch):
    """Req 8.3: the spinner is hidden even when the request raises."""
    spinner = SpinnerRecorder()
    _patch_st(
        monkeypatch,
        file_uploader=FakeUploadedFile("r.txt", "text/plain", b"data"),
        text_area="a real job description",
        button=True,
        spinner=spinner,
    )

    def _raise(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(app, "post_analysis", _raise)

    app.main()

    # __enter__ and __exit__ both ran despite the exception inside the block.
    assert spinner.entered == 1
    assert spinner.exited == 1


# --- Requirement 8.4: non-success -> backend detail or generic message ---


def test_extract_error_message_returns_backend_detail():
    """Req 8.4: a response carrying a ``detail`` returns that detail."""
    response = FakeResponse(status_code=500, json_data={"detail": "Boom"})
    assert app.extract_error_message(response) == "Boom"


def test_extract_error_message_generic_when_json_raises():
    """Req 8.4: a non-JSON body falls back to the generic error message."""
    response = FakeResponse(status_code=500, json_exc=ValueError("not json"))
    assert app.extract_error_message(response) == app.MSG_GENERIC_ERROR


def test_extract_error_message_generic_when_detail_absent():
    """Req 8.4: a JSON object without ``detail`` falls back to the generic message."""
    response = FakeResponse(status_code=500, json_data={})
    assert app.extract_error_message(response) == app.MSG_GENERIC_ERROR


def test_main_displays_backend_detail_on_non_success(monkeypatch):
    """Req 8.4: main surfaces the backend detail via st.error on a 4xx/5xx."""
    recorders = _patch_st(
        monkeypatch,
        file_uploader=FakeUploadedFile("r.txt", "text/plain", b"data"),
        text_area="a real job description",
        button=True,
    )
    monkeypatch.setattr(
        app,
        "post_analysis",
        lambda *a, **k: FakeResponse(status_code=422, json_data={"detail": "Bad input"}),
    )

    app.main()

    error_messages = [args[0] for args, _ in recorders["error"].calls]
    assert "Bad input" in error_messages


# --- Requirement 8.5: transport failure -> connection message ---


@pytest.mark.parametrize(
    "exc",
    [
        requests.exceptions.ConnectionError("no route"),
        requests.exceptions.Timeout("timed out"),
    ],
)
def test_main_shows_connection_error_on_transport_failure(monkeypatch, exc):
    """Req 8.5: connection failures and timeouts show the connection message."""
    recorders = _patch_st(
        monkeypatch,
        file_uploader=FakeUploadedFile("r.txt", "text/plain", b"data"),
        text_area="a real job description",
        button=True,
    )

    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(app, "post_analysis", _raise)

    app.main()

    error_messages = [args[0] for args, _ in recorders["error"].calls]
    assert app.MSG_CONNECTION_ERROR in error_messages


# --- Requirement 9.1: metric rendered with a % indicator ---


def test_metric_rendered_with_percent(monkeypatch):
    """Req 9.1: render_results passes a "<n>%" value to st.metric."""
    metric = Recorder()
    monkeypatch.setattr(app.st, "metric", metric)
    monkeypatch.setattr(app.st, "subheader", Recorder())
    monkeypatch.setattr(app.st, "info", Recorder())
    monkeypatch.setattr(app.st, "code", Recorder())
    monkeypatch.setattr(app.st, "markdown", Recorder())

    app.render_results({"percentage": 87, "improvements": [], "latex_code": "x"})

    assert len(metric.calls) == 1
    _, metric_kwargs = metric.calls[0]
    assert metric_kwargs.get("value") == "87%"
    assert app.format_percentage(87) == "87%"


# --- Requirement 9.3: empty improvements -> "no improvements" message ---


def test_empty_improvements_shows_no_improvements_message(monkeypatch):
    """Req 9.3: an empty improvements list shows the "no improvements" message."""
    info = Recorder()
    markdown = Recorder()
    monkeypatch.setattr(app.st, "info", info)
    monkeypatch.setattr(app.st, "markdown", markdown)
    monkeypatch.setattr(app.st, "metric", Recorder())
    monkeypatch.setattr(app.st, "subheader", Recorder())
    monkeypatch.setattr(app.st, "code", Recorder())

    app.render_results({"percentage": 50, "improvements": [], "latex_code": "x"})

    info_messages = [args[0] for args, _ in info.calls]
    assert app.MSG_NO_IMPROVEMENTS in info_messages
    # No improvement list items were rendered for an empty list.
    assert markdown.calls == []
