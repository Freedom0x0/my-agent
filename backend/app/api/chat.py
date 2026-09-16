"""POST /api/chat — entry point for the MiniMax agent."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..mcp.agent import ChatError, process_chat, process_chat_stream

logger = logging.getLogger(__name__)


def create_chat_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/chat")
    async def chat_route(payload: dict[str, Any]) -> dict[str, Any]:
        message = (payload.get("message") or "").strip()
        if not message:
            return {
                "error_code": "invalid_request",
                "reply": "消息不能为空",
                "tool_calls": [],
                "output_id": None,
                "sheets": [],
            }
        if len(message) > 4000:
            return {
                "error_code": "invalid_request",
                "reply": "消息过长（最多 4000 字）",
                "tool_calls": [],
                "output_id": None,
                "sheets": [],
            }
        file_ids = payload.get("file_ids") or []
        session_id = payload.get("session_id")
        if not session_id:
            session_id = uuid.uuid4().hex

        settings = get_settings()
        try:
            response = process_chat(
                session_id=session_id,
                user_message=message,
                file_ids=list(file_ids),
                settings=settings,
            )
            payload_out = response.to_dict()
            payload_out["session_id"] = session_id
            payload_out.setdefault("error_code", None)
            return payload_out
        except ChatError as exc:
            logger.warning("chat error: %s - %s", exc.code, exc.message)
            return {
                "session_id": session_id,
                "error_code": exc.code,
                "reply": exc.message,
                "tool_calls": [],
                "output_id": None,
                "sheets": [],
            }

    @router.post("/chat/stream")
    async def chat_stream_route(payload: dict[str, Any], request: Request) -> StreamingResponse:
        message = (payload.get("message") or "").strip()
        file_ids = list(payload.get("file_ids") or [])
        session_id = payload.get("session_id") or uuid.uuid4().hex

        async def _gen() -> AsyncIterator[str]:
            if not message:
                yield _sse({"type": "error", "code": "invalid_request", "message": "消息不能为空"})
                return
            if len(message) > 4000:
                yield _sse({"type": "error", "code": "invalid_request", "message": "消息过长（最多 4000 字）"})
                return

            async def _is_disc() -> bool:
                try:
                    return await request.is_disconnected()
                except Exception:
                    return False

            try:
                async for event in process_chat_stream(
                    session_id=session_id,
                    user_message=message,
                    file_ids=file_ids,
                    settings=get_settings(),
                    is_disconnected=_is_disc,
                ):
                    yield _sse(event)
            except ChatError as exc:
                yield _sse({"type": "error", "code": exc.code, "message": exc.message})
            except asyncio.CancelledError:
                return
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("stream chat crashed")
                yield _sse({"type": "error", "code": "internal_error", "message": str(exc)[:300]})

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"