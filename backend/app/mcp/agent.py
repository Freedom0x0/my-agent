"""MiniMax (Anthropic Messages API) agent loop."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from ..config import get_settings
from ..logging_setup import log_event
from .handlers import HANDLERS, truncate_result, validate_tool_input
from .prompts import SYSTEM_PROMPT
from .schemas import (
    MAX_MODEL_SECONDS,
    MAX_TOOL_CALLS,
    ToolCall,
    ToolResult,
)
from .session import Session
from .tools import TABLEX_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


class ChatError(RuntimeError):
    """Agent loop exited with a structured error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ChatResponse:
    """Final result returned to /api/chat."""

    def __init__(
        self,
        reply: str,
        tool_calls: list[dict[str, Any]],
        output_id: str | None = None,
        sheets: list[str] | None = None,
        error_code: str | None = None,
    ):
        self.reply = reply
        self.tool_calls = tool_calls
        self.output_id = output_id
        self.sheets = sheets or []
        self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "output_id": self.output_id,
            "sheets": self.sheets,
            **({"error_code": self.error_code} if self.error_code else {}),
        }


# Module-level indirection so tests can monkeypatch minimax_chat without rewriting the loop.
def minimax_chat(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    model: str,
    base_url: str,
    api_key: str,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """POST to the Anthropic Messages API and return the parsed JSON dict."""
    payload: dict[str, Any] = {
        "model": model,
        "system": system,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/v1/messages",
            json=payload,
            headers=headers,
            timeout=MAX_MODEL_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise ChatError("model_timeout", f"模型请求超时: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ChatError("model_error", f"模型请求失败: {exc}") from exc

    if response.status_code >= 400:
        raise ChatError(
            "model_error",
            f"模型返回错误 {response.status_code}: {response.text[:200]}",
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ChatError("model_invalid_response", f"模型响应不是 JSON: {exc}") from exc


ChatCaller = Callable[..., dict[str, Any]]
_default_chat_caller: ChatCaller = minimax_chat


def set_chat_caller(caller: ChatCaller | None) -> None:
    """Test hook: replace the module-level caller."""
    global _default_chat_caller
    _default_chat_caller = caller if caller is not None else minimax_chat


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    parts = [
        b.get("text", "")
        for b in content_blocks
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return "".join(parts)


def _build_first_user_text(user_message: str, session: Session) -> str:
    if not session.files:
        return user_message
    lines = [user_message, "", "## 可用文件"]
    for fid, info in session.files.items():
        name = info.get("original_name", "?")
        lines.append(f"- file_id=`{fid}` 名称=`{name}`")
    return "\n".join(lines)


def process_chat(
    session_id: str,
    user_message: str,
    file_ids: list[str] | None = None,
    *,
    store: Any | None = None,
    settings: Any | None = None,
    chat_caller: ChatCaller | None = None,
) -> ChatResponse:
    """Run one user turn through the agent loop and return the final response."""
    from .session import get_session_store  # local import for testability

    if not user_message.strip():
        raise ChatError("invalid_request", "消息不能为空")

    settings = settings or get_settings()
    store = store or get_session_store()
    session = store.get_or_create(session_id)
    caller = chat_caller or _default_chat_caller

    # Register any new file paths (tables still lazy — handlers load via tablex_upload).
    if file_ids:
        from ..db import get_file

        db_path = settings_data_dir(settings) / "metadata.db"
        for fid in file_ids:
            if fid in session.files:
                continue
            rec = get_file(db_path, fid)
            if rec is None:
                raise ChatError("file_not_found", f"未找到文件 {fid}")
            session.files[fid] = {
                "path": rec.stored_path,
                "sha256": rec.sha256,
                "original_name": rec.original_name,
            }

    if not settings.MODEL_BASE_URL or not settings.MODEL_API_KEY or not settings.MODEL_NAME:
        raise ChatError("model_not_configured", "MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME 未配置")

    # First user message carries file context so the agent knows which file_ids are valid.
    is_first = not session.messages
    content_text = _build_first_user_text(user_message, session) if is_first else user_message
    session.messages.append({"role": "user", "content": content_text})

    with session.lock:
        for _ in range(MAX_TOOL_CALLS):
            try:
                response = caller(
                    messages=session.messages,
                    tools=TABLEX_TOOL_DEFINITIONS,
                    system=SYSTEM_PROMPT,
                    model=settings.MODEL_NAME,
                    base_url=settings.MODEL_BASE_URL,
                    api_key=settings.MODEL_API_KEY,
                )
            except ChatError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                raise ChatError("model_error", f"模型调用失败: {exc}") from exc

            stop_reason = response.get("stop_reason")
            content_blocks = response.get("content") or []

            if stop_reason == "end_turn":
                text = _extract_text(content_blocks)
                session.messages.append({"role": "assistant", "content": content_blocks})
                session.touch()
                store.persist_messages(session)
                return ChatResponse(
                    reply=text,
                    tool_calls=list(session.tool_calls_log),
                    output_id=session.output_id,
                    sheets=list(session.tables.keys()),
                )

            if stop_reason == "max_tokens":
                session.messages.append({"role": "assistant", "content": content_blocks})
                store.persist_messages(session)
                return ChatResponse(
                    reply="模型输出过长，请简化需求",
                    tool_calls=list(session.tool_calls_log),
                    output_id=session.output_id,
                    sheets=list(session.tables.keys()),
                    error_code="model_truncated",
                )

            if stop_reason == "tool_use":
                session.messages.append({"role": "assistant", "content": content_blocks})
                tool_results: list[dict[str, Any]] = []
                for block in content_blocks:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tool_call = ToolCall(
                        tool_use_id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input") or {},
                    )
                    validation = validate_tool_input(tool_call.name, tool_call.input, session)
                    tool_status = "ok"
                    if not validation.ok:
                        result = ToolResult(success=False, summary="参数校验失败", error=validation.error)
                        tool_status = "error"
                    else:
                        tool_started = time.perf_counter()
                        try:
                            result = HANDLERS[tool_call.name].fn(tool_call, session)
                            if not result.success:
                                tool_status = "error"
                        except Exception as exc:
                            logger.exception("handler %s failed", tool_call.name)
                            result = ToolResult(success=False, summary="执行失败", error=str(exc)[:300])
                            tool_status = "error"
                        finally:
                            tool_duration_ms = int((time.perf_counter() - tool_started) * 1000)
                            log_event(
                                logging.INFO if tool_status == "ok" else logging.WARNING,
                                f"tool {tool_call.name} {tool_status} {tool_duration_ms}ms",
                                request_id=getattr(session, "request_id", None),
                            )

                    result_text = truncate_result(result)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call.tool_use_id,
                            "content": result_text,
                        }
                    )
                    log_entry: dict[str, Any] = {
                        "tool": tool_call.name,
                        "status": "ok" if result.success else "error",
                        "summary": result.summary,
                    }
                    if result.data and "output_id" in result.data:
                        log_entry["output_id"] = result.data["output_id"]
                    session.tool_calls_log.append(log_entry)
                session.messages.append({"role": "user", "content": tool_results})
                session.touch()
                store.persist_messages(session)
                continue

            # Unknown stop_reason — bail.
            raise ChatError(
                "model_unknown_stop_reason",
                f"模型返回未知 stop_reason: {stop_reason}",
            )

    raise ChatError("too_many_steps", "处理步骤过多，请精简需求")


def settings_data_dir(settings: Any) -> Any:
    """Return the absolute APP_DATA_DIR (small wrapper to keep imports tidy)."""
    from pathlib import Path

    return Path(settings.APP_DATA_DIR).resolve()