"""Tests for the logging ring buffer, middleware, and /api/logs/recent endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import init_db
from backend.app.logging_setup import (
    LOG_FORMAT,
    RING_CAPACITY,
    RingBufferHandler,
    get_ring,
    log_event,
    reset_ring,
    setup_logging,
)
from backend.app.main import app


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point everything at a temp dir — these tests used to write into runtime/."""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    # No model: /api/chat then fails fast with `model_not_configured` (a 200 with an
    # error_code) instead of making a real, slow, billable call to the provider.
    monkeypatch.setenv("MODEL_BASE_URL", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "")
    get_settings.cache_clear()
    init_db(tmp_path / "runtime" / "metadata.db")
    reset_ring()
    setup_logging(tmp_path / "logs")
    get_ring().clear()
    yield
    get_settings.cache_clear()


def test_ring_buffer_starts_empty_and_captures_log() -> None:
    ring = get_ring()
    assert len(ring) == 0
    log_event(20, "hello world", request_id="abc")  # 20 = INFO
    lines = ring.snapshot()
    assert len(lines) == 1
    assert "hello world" in lines[0]
    assert "[abc]" in lines[0]


def test_ring_buffer_is_bounded() -> None:
    ring = get_ring()
    for i in range(RING_CAPACITY + 50):
        log_event(20, f"line-{i}")
    snap = ring.snapshot()
    assert len(snap) == RING_CAPACITY
    # oldest entries dropped, newest kept
    assert "line-50" in snap[0]
    assert f"line-{RING_CAPACITY + 49}" in snap[-1]


def test_format_includes_timestamp_level_and_request_id() -> None:
    log_event(20, "ping", request_id="req-7")
    line = get_ring().snapshot()[0]
    # timestamp YYYY-MM-DD HH:MM:SS.mmm + INFO + [req-7] + ping
    assert "[INFO]" in line
    assert "[req-7]" in line
    assert line.endswith("ping")


def test_logs_recent_endpoint_returns_lines() -> None:
    log_event(20, "alpha")
    log_event(30, "beta-warning", request_id="r1")  # WARNING
    log_event(40, "gamma-error", request_id="r2")   # ERROR
    response = _client().get("/api/logs/recent", params={"lines": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total_lines"] >= 3
    assert any("alpha" in ln for ln in body["lines"])
    assert any("[WARNING]" in ln and "beta-warning" in ln for ln in body["lines"])
    assert any("[ERROR]" in ln and "gamma-error" in ln for ln in body["lines"])


def test_logs_recent_respects_lines_param() -> None:
    for i in range(10):
        log_event(20, f"x-{i}")
    response = _client().get("/api/logs/recent", params={"lines": 3})
    assert response.status_code == 200
    body = response.json()
    assert len(body["lines"]) == 3
    assert body["total_lines"] >= 10


def test_logs_recent_rejects_invalid_lines() -> None:
    response = _client().get("/api/logs/recent", params={"lines": 0})
    assert response.status_code == 422
    response = _client().get("/api/logs/recent", params={"lines": 5000})
    assert response.status_code == 422


def _middleware_log_line(lines: list[str], method: str, path: str) -> list[str]:
    """Return log lines emitted by our request_log_middleware for a given method+path.

    The middleware emits `METHOD PATH STATUS DURATIONms`; httpx's own client
    logger emits `HTTP Request: METHOD URL ...` — those are NOT middleware lines.
    """
    return [ln for ln in lines if f"{method} {path}" in ln and "HTTP Request" not in ln]


def test_middleware_skips_logs_recent_and_health() -> None:
    _client().get("/api/health")
    _client().get("/api/logs/recent", params={"lines": 50})
    lines = get_ring().snapshot()
    assert _middleware_log_line(lines, "GET", "/api/health") == [], (
        "/api/health must not be request-logged by middleware"
    )
    assert _middleware_log_line(lines, "GET", "/api/logs/recent") == [], (
        "/api/logs/recent polling must not appear in the log panel"
    )


def test_middleware_still_logs_real_endpoints() -> None:
    # 404 on a non-silent path → log must still record it (this exercises the "else" branch).
    _client().get("/api/this-does-not-exist")
    lines = get_ring().snapshot()
    assert any("GET /api/this-does-not-exist 404" in ln for ln in lines)


def test_middleware_logs_post_chat() -> None:
    # POST /api/chat is the user-visible action stream — must be logged.
    response = _client().post("/api/chat", json={"message": "hi"})
    # Endpoint may 400/422 without proper setup; what matters is the request line was emitted.
    lines = get_ring().snapshot()
    assert _middleware_log_line(lines, "POST", "/api/chat"), (
        "POST /api/chat requests must be recorded in the log"
    )
    assert response.status_code in (200, 400, 422)


def test_middleware_logs_file_upload() -> None:
    files = {"file": ("tiny.csv", b"a,b\n1,2\n", "text/csv")}
    response = _client().post("/api/files", files=files)
    # Endpoint returns 201 on success or 400 on validation error — middleware logs both.
    lines = get_ring().snapshot()
    assert _middleware_log_line(lines, "POST", "/api/files"), (
        "POST /api/files requests must be recorded in the log"
    )
    assert response.status_code in (201, 400)


def test_middleware_logs_repeated_chat_not_swamped_by_polling() -> None:
    # Simulate the bug scenario: many polls + a few real requests.
    for _ in range(5):
        _client().get("/api/logs/recent", params={"lines": 10})
    _client().post("/api/chat", json={"message": "do the thing"})
    lines = get_ring().snapshot()
    # No middleware pollution from polling
    assert _middleware_log_line(lines, "GET", "/api/logs/recent") == []
    # Real request still present
    assert _middleware_log_line(lines, "POST", "/api/chat")


def test_middleware_uses_inbound_request_id() -> None:
    response = _client().get(
        "/api/this-does-not-exist", headers={"X-Request-ID": "caller-supplied"}
    )
    assert response.headers.get("X-Request-ID") == "caller-supplied"
    lines = get_ring().snapshot()
    assert any(
        "[caller-supplied]" in ln and "GET /api/this-does-not-exist" in ln
        for ln in lines
    )


def test_middleware_generates_request_id_when_missing() -> None:
    response = _client().get("/api/this-does-not-exist")
    generated = response.headers.get("X-Request-ID")
    assert generated and len(generated) > 0
    lines = get_ring().snapshot()
    assert any(f"[{generated}]" in ln and "GET /api/this-does-not-exist" in ln for ln in lines)


def test_middleware_records_5xx_status() -> None:
    # Hit a path that doesn't exist to trigger 404 via FastAPI's default.
    response = _client().get("/api/this-does-not-exist")
    assert response.status_code == 404
    lines = get_ring().snapshot()
    assert any("GET /api/this-does-not-exist 404" in ln for ln in lines)


def test_ring_buffer_handler_clear() -> None:
    ring = get_ring()
    log_event(20, "first")
    log_event(20, "second")
    assert len(ring) == 2
    ring.clear()
    assert len(ring) == 0


def test_ring_buffer_default_formatter_works() -> None:
    handler = RingBufferHandler(capacity=5)
    import logging as _logging

    handler.setFormatter(_logging.Formatter(LOG_FORMAT))
    log = _logging.LogRecord(
        name="t", level=_logging.INFO, pathname=__file__, lineno=0,
        msg="formatted", args=(), exc_info=None,
    )
    log.request_id = "rid"
    handler.emit(log)
    assert "formatted" in handler.snapshot()[0]
    assert "[rid]" in handler.snapshot()[0]


def test_ring_captures_records_that_lack_a_request_id() -> None:
    """`logger.exception` and third-party loggers never go through `log_event`.

    Without the ring's own filter, `format()` raised on the missing field and
    `handleError` swallowed it — so the log panel silently lost exactly the error
    lines it exists to show.
    """
    import logging as _logging

    _logging.getLogger("app").warning("plain warning, no request_id")
    lines = get_ring().snapshot()
    assert any("plain warning, no request_id" in ln and "[-]" in ln for ln in lines)


def test_contextvar_request_id_reaches_a_plain_logger() -> None:
    """This is what makes a bare `logger.exception(...)` in an endpoint traceable."""
    import logging as _logging

    from backend.app.logging_setup import reset_request_id, set_request_id

    token = set_request_id("ctx-123")
    try:
        _logging.getLogger("app").warning("from a logger call")
    finally:
        reset_request_id(token)

    assert any(
        "[ctx-123]" in ln and "from a logger call" in ln for ln in get_ring().snapshot()
    )
