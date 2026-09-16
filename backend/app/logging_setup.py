"""Centralised logging setup: stderr + daily-rotated file + in-memory ring buffer.

The ring buffer is the source of truth for the `/api/logs/recent` endpoint.
The file handler is for operators who need to read logs after a restart.
`setup_logging` is idempotent so re-import is safe.
"""
from __future__ import annotations

import logging
from collections import deque
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(request_id)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

RING_CAPACITY = 1000


class RingBufferHandler(logging.Handler):
    """Thread-safe bounded deque of formatted log lines."""

    def __init__(self, capacity: int = RING_CAPACITY) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._buffer.append(self.format(record))
        except Exception:  # pragma: no cover - defensive
            self.handleError(record)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


_RING: RingBufferHandler | None = None
_RING_LOCK = Lock()


def get_ring() -> RingBufferHandler:
    """Return the process-wide ring handler, creating it on first use."""
    global _RING
    if _RING is None:
        with _RING_LOCK:
            if _RING is None:
                ring = RingBufferHandler(RING_CAPACITY)
                ring.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
                _RING = ring
    return _RING


def reset_ring() -> None:
    """Test hook: drop the singleton so the next call recreates it."""
    global _RING
    with _RING_LOCK:
        _RING = None


class _RequestIdFilter(logging.Filter):
    """Inject `request_id='-'` so the format string never KeyErrors."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = "-"
        return True


def setup_logging(log_dir: Path | str) -> Path:
    """Configure the root logger with stderr + file + ring handlers.

    Removes any previously attached handlers so this is safe to call multiple
    times (e.g. when tests re-import the app).
    """
    log_path = Path(log_dir).resolve()
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "backend.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    rid_filter = _RequestIdFilter()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(rid_filter)
    root.addHandler(stream)

    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(rid_filter)
    root.addHandler(file_handler)

    ring = get_ring()
    root.addHandler(ring)

    # Silence chatty third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return log_path


def log_event(
    level: int,
    message: str,
    *,
    request_id: str | None = None,
    **extra: Any,
) -> None:
    """Emit a log record under the `app` logger, with optional `request_id`."""
    payload: dict[str, Any] = {"request_id": request_id or "-"}
    payload.update(extra)
    logging.getLogger("app").log(level, message, extra=payload)
