"""Request-level access logging.

Deliberately a raw ASGI middleware rather than `BaseHTTPMiddleware`: the latter
spawns the endpoint in a child task, which interferes with streaming responses
(`/api/chat/stream` never finishes until the turn does) and with client
disconnects. Staying in the same task keeps contextvars — and the SSE stream —
behaving normally.
"""
from __future__ import annotations

import logging
import uuid
from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..logging_setup import log_event, reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"

# Endpoints the browser polls or that would otherwise flood the log panel. Without
# this, 5 log-panel polls drown out the one request you actually want to see.
SILENT_PATHS = frozenset({"/api/health", "/api/logs/recent"})


def _inbound_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name.decode("latin-1").lower() == REQUEST_ID_HEADER.lower():
            decoded = value.decode("latin-1").strip()
            if decoded:
                return decoded
    return None


class RequestLogMiddleware:
    """Logs `METHOD PATH STATUS DURATIONms` for every non-silent request.

    Also threads a request id through the whole call: the inbound `X-Request-ID`
    (or a fresh one) goes into a contextvar so any log line emitted while serving
    the request picks it up, and is echoed back on the response for the client to
    quote in a bug report.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        request_id = _inbound_request_id(scope) or uuid.uuid4().hex

        token = set_request_id(request_id)
        status = 500
        started = perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = int((perf_counter() - started) * 1000)
            reset_request_id(token)
            if path not in SILENT_PATHS:
                level = (
                    logging.INFO
                    if status < 400
                    else logging.WARNING
                    if status < 500
                    else logging.ERROR
                )
                log_event(
                    level,
                    f"{method} {path} {status} {duration_ms}ms",
                    request_id=request_id,
                )