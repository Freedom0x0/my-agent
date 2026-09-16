"""POST /api/chat — entry point for the MiniMax agent."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ..config import get_settings
from ..mcp.agent import ChatError, process_chat

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
            import uuid as _uuid

            session_id = _uuid.uuid4().hex

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

    return router