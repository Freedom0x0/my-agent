"""MiniMax (Anthropic Messages API) agent loop."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Callable

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
StreamCaller = Callable[..., AsyncIterator[dict[str, Any]]]
_default_chat_caller: ChatCaller = minimax_chat
_default_stream_caller: StreamCaller | None = None


def set_chat_caller(caller: ChatCaller | None) -> None:
    """Test hook: replace the module-level caller."""
    global _default_chat_caller
    _default_chat_caller = caller if caller is not None else minimax_chat


async def minimax_chat_stream(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    model: str,
    base_url: str,
    api_key: str,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> AsyncIterator[dict[str, Any]]:
    """Stream from the Anthropic Messages API; yield normalized events.

    Event types yielded:
      - {"type": "model_meta", "message_id": str}
      - {"type": "text", "delta": str}
      - {"type": "tool_use_start", "id": str, "name": str}
      - {"type": "tool_use_delta", "id": str, "partial_json": str}
      - {"type": "tool_use_end", "id": str}
      - {"type": "message_done", "stop_reason": str, "content_blocks": list}
      - {"type": "error", "code": str, "message": str}
    """
    payload: dict[str, Any] = {
        "model": model,
        "system": system,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/v1/messages",
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(MAX_MODEL_SECONDS),
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise ChatError(
                        "model_error",
                        f"模型返回错误 {resp.status_code}: {body[:200]!r}",
                    )
                # Accumulate content blocks so caller can rebuild the full message.
                blocks: dict[int, dict[str, Any]] = {}
                stop_reason: str | None = None
                message_id: str | None = None
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    etype = evt.get("type")
                    if etype == "message_start":
                        msg = evt.get("message") or {}
                        message_id = msg.get("id")
                        yield {"type": "model_meta", "message_id": message_id or ""}
                    elif etype == "content_block_start":
                        idx = evt.get("index", 0)
                        block = evt.get("content_block") or {}
                        btype = block.get("type")
                        if btype == "text":
                            blocks[idx] = {"type": "text", "text": ""}
                        elif btype == "tool_use":
                            blocks[idx] = {
                                "type": "tool_use",
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input_json": "",
                                "input": {},
                            }
                            yield {
                                "type": "tool_use_start",
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                            }
                    elif etype == "content_block_delta":
                        idx = evt.get("index", 0)
                        delta = evt.get("delta") or {}
                        d_type = delta.get("type")
                        block = blocks.get(idx)
                        if d_type == "text_delta" and block is not None and block.get("type") == "text":
                            chunk = delta.get("text", "")
                            block["text"] += chunk
                            yield {"type": "text", "delta": chunk}
                        elif d_type == "input_json_delta" and block is not None and block.get("type") == "tool_use":
                            partial = delta.get("partial_json", "")
                            block["input_json"] += partial
                            yield {
                                "type": "tool_use_delta",
                                "id": block.get("id", ""),
                                "partial_json": partial,
                            }
                    elif etype == "content_block_stop":
                        idx = evt.get("index", 0)
                        block = blocks.get(idx)
                        if block is not None and block.get("type") == "tool_use":
                            raw = block.get("input_json") or ""
                            try:
                                block["input"] = json.loads(raw) if raw else {}
                            except json.JSONDecodeError:
                                block["input"] = {}
                            yield {"type": "tool_use_end", "id": block.get("id", "")}
                    elif etype == "message_delta":
                        delta = evt.get("delta") or {}
                        if "stop_reason" in delta and delta["stop_reason"]:
                            stop_reason = delta["stop_reason"]
                    elif etype == "message_stop":
                        break
                content_blocks = [blocks[k] for k in sorted(blocks.keys())]
                yield {
                    "type": "message_done",
                    "stop_reason": stop_reason or "end_turn",
                    "content_blocks": content_blocks,
                }
    except ChatError:
        raise
    except httpx.TimeoutException as exc:
        raise ChatError("model_timeout", f"模型请求超时: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ChatError("model_error", f"模型请求失败: {exc}") from exc


def set_stream_caller(caller: StreamCaller | None) -> None:
    """Test hook: replace the module-level streaming caller."""
    global _default_stream_caller
    _default_stream_caller = caller


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


def _process_chat_setup(
    session_id: str,
    user_message: str,
    file_ids: list[str] | None,
    store: Any | None,
    settings: Any | None,
):
    """Shared sync setup used by both process_chat and process_chat_stream."""
    from .session import get_session_store  # local import for testability

    if not user_message.strip():
        raise ChatError("invalid_request", "消息不能为空")

    settings = settings or get_settings()
    store = store or get_session_store()
    session = store.get_or_create(session_id)

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

    is_first = not session.messages
    content_text = _build_first_user_text(user_message, session) if is_first else user_message
    session.messages.append({"role": "user", "content": content_text})

    return session, store, settings


async def process_chat_stream(
    session_id: str,
    user_message: str,
    file_ids: list[str] | None = None,
    *,
    store: Any | None = None,
    settings: Any | None = None,
    stream_caller: StreamCaller | None = None,
    is_disconnected: Callable[[], Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator: same loop as process_chat but yields SSE events."""
    session, store, settings = _process_chat_setup(
        session_id, user_message, file_ids, store, settings,
    )
    caller = stream_caller or _default_stream_caller or minimax_chat_stream

    async def _check_disc() -> bool:
        if is_disconnected is None:
            return False
        result = is_disconnected()
        if hasattr(result, "__await__"):
            return bool(await result)  # type: ignore[func-returns-value]
        return bool(result)

    for _ in range(MAX_TOOL_CALLS):
        if await _check_disc():
            return

        yield {"type": "model_call"}

        content_blocks: list[dict[str, Any]] = []
        stop_reason: str | None = None
        try:
            async for evt in caller(
                messages=session.messages,
                tools=TABLEX_TOOL_DEFINITIONS,
                system=SYSTEM_PROMPT,
                model=settings.MODEL_NAME,
                base_url=settings.MODEL_BASE_URL,
                api_key=settings.MODEL_API_KEY,
            ):
                etype = evt.get("type")
                if etype == "text":
                    yield {"type": "text", "delta": evt.get("delta", "")}
                elif etype == "tool_use_start":
                    yield {
                        "type": "tool_start",
                        "name": evt.get("name", ""),
                        "id": evt.get("id", ""),
                    }
                elif etype == "message_done":
                    stop_reason = evt.get("stop_reason")
                    content_blocks = list(evt.get("content_blocks") or [])
            if stop_reason is None:
                raise ChatError("model_invalid_response", "模型未返回 stop_reason")
        except ChatError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise ChatError("model_error", f"模型调用失败: {exc}") from exc

        yield {"type": "model_response", "stop_reason": stop_reason}

        if stop_reason == "end_turn":
            text = _extract_text(content_blocks)
            session.messages.append({"role": "assistant", "content": content_blocks})
            session.touch()
            store.persist_messages(session)
            yield {
                "type": "done",
                "reply": text,
                "tool_calls": list(session.tool_calls_log),
                "output_id": session.output_id,
                "sheets": list(session.tables.keys()),
            }
            return

        if stop_reason == "max_tokens":
            session.messages.append({"role": "assistant", "content": content_blocks})
            store.persist_messages(session)
            yield {
                "type": "error",
                "code": "model_truncated",
                "message": "模型输出过长，请简化需求",
                "reply": "模型输出过长，请简化需求",
                "tool_calls": list(session.tool_calls_log),
                "output_id": session.output_id,
                "sheets": list(session.tables.keys()),
            }
            return

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
                yield {
                    "type": "tool_end",
                    "name": tool_call.name,
                    "summary": result.summary,
                    "status": tool_status,
                    "output_id": result.data.get("output_id") if isinstance(result.data, dict) else None,
                }
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