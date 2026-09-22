"""MiniMax (Anthropic Messages API) agent loop."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Callable

import httpx

from ..config import get_settings
from ..logging_setup import current_request_id, log_event
from .handlers import HANDLERS, truncate_result
from .prompts import SYSTEM_PROMPT
from .schemas import (
    MAX_MODEL_SECONDS,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALLS,
    ToolCall,
    ToolResult,
)
from .session import Session
from .workflow import (
    META_TOOL_NAME,
    WorkflowError,
    agent_tool_definitions,
    normalize_graph,
    public_graph,
    render_graph_context,
)


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
        output_name: str | None = None,
        sheets: list[str] | None = None,
        error_code: str | None = None,
        stage: str = "drafting",
        graph: dict[str, Any] | None = None,
    ):
        self.reply = reply
        self.tool_calls = tool_calls
        self.output_id = output_id
        self.output_name = output_name
        self.sheets = sheets or []
        self.error_code = error_code
        self.stage = stage
        self.graph = graph

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "output_id": self.output_id,
            "output_name": self.output_name,
            "sheets": self.sheets,
            "stage": self.stage,
            "graph": self.graph,
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
    max_tokens: int = MAX_OUTPUT_TOKENS,
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
    max_tokens: int = MAX_OUTPUT_TOKENS,
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
                usage: dict[str, Any] = {}
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
                        # input_tokens arrives here; output_tokens lands on message_delta.
                        usage.update(msg.get("usage") or {})
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
                        usage.update(evt.get("usage") or {})
                    elif etype == "message_stop":
                        break
                content_blocks = [blocks[k] for k in sorted(blocks.keys())]
                yield {
                    "type": "message_done",
                    "stop_reason": stop_reason or "end_turn",
                    "content_blocks": content_blocks,
                    "usage": usage,
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


def _last_output_name(session: Any) -> str | None:
    """Walk session.tool_calls_log tail to find the most recent output_name."""
    for entry in reversed(session.tool_calls_log):
        if not isinstance(entry, dict):
            continue
        name = entry.get("output_name")
        if name:
            return name
    return None


def _tool_log_line(
    session: Any,
    tool_call: ToolCall,
    status: str,
    duration_ms: int,
    summary: str,
) -> str:
    """One line per tool run, carrying enough context to trace it afterwards.

    The log format renders only `%(message)s`, so anything not in here is invisible
    in the file — `session` and `file` are what let you reconstruct which
    conversation and which sheet a slow or failing call belonged to.
    """
    parts = [
        f"tool {tool_call.name} {status} {duration_ms}ms",
        f"session={session.session_id}",
    ]
    file_id = tool_call.input.get("file_id")
    if file_id:
        parts.append(f"file={file_id}")
    if summary:
        text = summary if len(summary) <= 120 else summary[:117] + "..."
        parts.append(f"| {text}")
    return " ".join(parts)


def _log_model_round(
    session: Any,
    stop_reason: str | None,
    round_ms: int,
    content_blocks: list[dict[str, Any]],
    usage: dict[str, Any],
) -> None:
    """One line per model round. Both loops log through here so the numbers are comparable.

    `cache_read` is the one to watch when tuning cost: the tool schemas dominate the
    request (they are ~85% of the fixed payload), so a hit there is where the money is.
    """
    log_event(
        logging.INFO,
        f"model round {stop_reason} {round_ms}ms blocks={len(content_blocks)}"
        f" tokens_in={usage.get('input_tokens', '?')}"
        f" tokens_out={usage.get('output_tokens', '?')}"
        f" cache_read={usage.get('cache_read_input_tokens', '?')}"
        f" cache_write={usage.get('cache_creation_input_tokens', '?')}"
        f" session={session.session_id}",
        request_id=getattr(session, "request_id", None),
    )


def _ui_append(
    session: Any,
    role: str,
    content: str = "",
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> None:
    """Append one UI-shaped turn to the session transcript (persisted, then replayed).

    Kept separate from `session.messages` (Anthropic shape, model context): the UI
    transcript carries the interleaved text/tool `segments` the client renders.
    """
    calls = list(tool_calls or [])
    for entry in calls:
        # A tool that never reported back would otherwise persist as `running`.
        if entry.get("status") not in ("ok", "error"):
            entry["status"] = "error"
    session.ui_messages.append({
        "role": role,
        "content": content,
        "tool_calls": calls,
        "segments": list(segments or []),
    })


# ponytail: flat caps per file; widen if real files routinely exceed them.
_MAX_SHEETS_IN_CONTEXT = 10
_MAX_COLS_PER_SHEET = 40


def _render_sheet_structure(inspection: Any) -> list[str]:
    """`工作表 X（n 行 × m 列）：col:type, …` + its data issues.

    The model has to commit a whole graph in one shot, so it needs the *real*
    sheet and column names up front. Without them it guesses (`Sheet1`) and the
    graph fails at execution — see `09-18-workflow-eval-set`.
    """
    sheets = (inspection or {}).get("sheets") or []
    lines: list[str] = []
    for sheet in sheets[:_MAX_SHEETS_IN_CONTEXT]:
        cols = sheet.get("columns") or []
        shown = ", ".join(f"{c.get('name')}:{c.get('inferred_type', '?')}" for c in cols[:_MAX_COLS_PER_SHEET])
        if len(cols) > _MAX_COLS_PER_SHEET:
            shown += f", …（共 {len(cols)} 列）"
        lines.append(
            f"  - 工作表 `{sheet.get('name')}`"
            f"（{sheet.get('row_count', '?')} 行 × {sheet.get('column_count', '?')} 列）：{shown}"
        )
        for issue in sheet.get("issues") or []:
            # `message` already names the column ("列 日期 存在多种日期格式"),
            # so no prefix — it would read "列 `日期` 列 日期 存在…".
            lines.append(f"      ⚠ {issue.get('message') or issue.get('code', '')}")
    if len(sheets) > _MAX_SHEETS_IN_CONTEXT:
        lines.append(f"  - …（共 {len(sheets)} 个工作表）")
    return lines


def _build_user_text(user_message: str, session: Session) -> str:
    """First message carries the available files; every message carries the graph."""
    lines = [user_message]
    if not session.messages and session.files:
        lines += ["", "## 可用文件"]
        for fid, info in session.files.items():
            name = info.get("original_name", "?")
            lines.append(f"- file_id=`{fid}` 名称=`{name}`")
            lines.extend(_render_sheet_structure(info.get("inspection")))
    if session.graph:
        lines += ["", render_graph_context(session.graph)]
    return "\n".join(lines)


def _handle_tool_call(session: Session, tool_call: ToolCall) -> tuple[ToolResult, bool]:
    """Handle one tool_use block. Returns (result, graph_submitted).

    The tablex_* tools are node types, not actions: calling one directly is a
    mistake that gets handed back to the model. `tablex_propose_workflow` is the
    only executable action — it stores the graph and the caller stops the loop.

    Never raises: every failure becomes a failed ToolResult the model can fix.
    """
    started = time.perf_counter()
    submitted = False
    if tool_call.name == META_TOOL_NAME:
        try:
            session.graph = normalize_graph(tool_call.input)
            session.stage = "awaiting_approval"
            submitted = True
            result = ToolResult(
                success=True,
                summary="工作流已生成，等待用户批准。",
                data={"stage": session.stage},
            )
        except WorkflowError as exc:
            result = ToolResult(success=False, summary="工作流图不合法", error=str(exc)[:300])
    elif tool_call.name in HANDLERS:
        result = ToolResult(
            success=False,
            summary="工具不能直接调用",
            error=(
                f"{tool_call.name} 只能作为工作流图的节点类型，不会被执行。"
                f"请用 {META_TOOL_NAME} 提交完整的工作流图。"
            ),
        )
    else:
        result = ToolResult(success=False, summary="未知工具", error=f"未知工具: {tool_call.name}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    log_summary = result.summary
    if not result.success and result.error:
        log_summary = f"{result.summary}: {result.error}"
    log_event(
        logging.INFO if result.success else logging.WARNING,
        _tool_log_line(session, tool_call, "ok" if result.success else "error", duration_ms, log_summary),
        request_id=getattr(session, "request_id", None),
    )
    return result, submitted


def _start_turn(session: Session, store: Any) -> None:
    """Reset this turn's stage, keeping SQLite in agreement with memory.

    `drafting` is a transient "the model is thinking" value and is never
    persisted. A graph that already exists is still unapproved, so the session's
    stable stage is `awaiting_approval` — restore it and write it back here,
    *before* the turn runs.

    Doing it at entry rather than on each exit is deliberate: the response is
    built from `session.stage` on the way out, so a turn that ends without a new
    graph (`end_turn` text-only, `max_tokens`, unknown stop reason,
    `too_many_steps`, or an unexpected exception) would otherwise report
    `drafting` while the DB still said `awaiting_approval` — and a reload would
    silently flip it back to a stage the user may have just asked to change.
    """
    if session.graph is None:
        session.stage = "drafting"
        return
    session.stage = "awaiting_approval"
    store.persist_workflow(session)


def _run_tool_round(
    session: Session, content_blocks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    """Handle every tool_use block in one model round.

    Returns (tool_results, graph_submitted). No handler is ever executed.
    """
    tool_results: list[dict[str, Any]] = []
    submitted = False
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_call = ToolCall(
            tool_use_id=block.get("id", ""),
            name=block.get("name", ""),
            input=block.get("input") or {},
        )
        result, call_submitted = _handle_tool_call(session, tool_call)
        submitted = submitted or call_submitted
        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_call.tool_use_id,
                "content": truncate_result(result),
            }
        )
        session.tool_calls_log.append(
            {
                "tool": tool_call.name,
                "status": "ok" if result.success else "error",
                "summary": result.summary,
            }
        )
    return tool_results, submitted


def _public_graph(graph: Any) -> dict[str, Any] | None:
    """Graph shaped for the client: every node carries its derived `seq`.

    `/api/chat` and `GET /api/sessions/{id}/workflow` must agree, so both go
    through here. Otherwise the client would have to reimplement the Kahn +
    heap tie-break in TypeScript to number the nodes.
    """
    return public_graph(graph) if graph else None


def _make_response(session: Session, reply: str, error_code: str | None = None) -> ChatResponse:
    return ChatResponse(
        reply=reply,
        tool_calls=list(session.tool_calls_log),
        output_id=session.output_id,
        output_name=_last_output_name(session),
        sheets=list(session.tables.keys()),
        error_code=error_code,
        stage=session.stage,
        graph=_public_graph(session.graph),
    )


def _finish_submitted(
    session: Session,
    store: Any,
    user_message: str,
    content_blocks: list[dict[str, Any]],
    tool_log_start: int,
) -> str:
    """Close the turn on a submitted graph: persist it and stop — nothing executes.

    The trailing assistant message keeps the history alternating, so the next
    turn's user message doesn't follow the tool_result user message directly.
    """
    store.persist_workflow(session)
    text = _extract_text(content_blocks) or "工作流图已生成，等待你批准。"
    session.messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
    session.touch()
    _ui_append(session, "user", user_message)
    _ui_append(session, "assistant", text, tool_calls=session.tool_calls_log[tool_log_start:])
    store.persist_messages(session)
    return text


def process_chat(
    session_id: str,
    user_message: str,
    file_ids: list[str] | None = None,
    *,
    store: Any | None = None,
    settings: Any | None = None,
    chat_caller: ChatCaller | None = None,
) -> ChatResponse:
    """Run one user turn through the agent loop and return the final response.

    The model *compiles* a workflow graph (`tablex_propose_workflow`); no node is
    executed here. Execution happens after the user approves, in the execution
    engine.
    """
    session, store, settings = _process_chat_setup(
        session_id, user_message, file_ids, store, settings,
    )
    caller = chat_caller or _default_chat_caller

    tool_log_start = len(session.tool_calls_log)

    with session.lock:
        for _ in range(MAX_TOOL_CALLS):
            round_started = time.perf_counter()
            try:
                response = caller(
                    messages=session.messages,
                    tools=agent_tool_definitions(),
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
            _log_model_round(
                session,
                stop_reason,
                int((time.perf_counter() - round_started) * 1000),
                content_blocks,
                response.get("usage") or {},
            )

            if stop_reason == "end_turn":
                text = _extract_text(content_blocks)
                session.messages.append({"role": "assistant", "content": content_blocks})
                session.touch()
                # The UI transcript is written only once the turn reaches a terminal
                # state, so a failed turn leaves no dangling user bubble behind.
                # ponytail: non-stream turns get no interleaved `segments` (the UI reads
                # `tool_calls` instead). None of the UI calls this path; wire it up if one does.
                _ui_append(session, "user", user_message)
                _ui_append(session, "assistant", text, tool_calls=session.tool_calls_log[tool_log_start:])
                store.persist_messages(session)
                return _make_response(session, text)

            if stop_reason == "max_tokens":
                session.messages.append({"role": "assistant", "content": content_blocks})
                _ui_append(session, "user", user_message)
                _ui_append(
                    session,
                    "assistant",
                    "模型输出过长，请简化需求",
                    tool_calls=session.tool_calls_log[tool_log_start:],
                )
                store.persist_messages(session)
                return _make_response(session, "模型输出过长，请简化需求", error_code="model_truncated")

            if stop_reason == "tool_use":
                session.messages.append({"role": "assistant", "content": content_blocks})
                tool_results, submitted = _run_tool_round(session, content_blocks)
                session.messages.append({"role": "user", "content": tool_results})
                session.touch()
                if submitted:
                    text = _finish_submitted(
                        session, store, user_message, content_blocks, tool_log_start
                    )
                    return _make_response(session, text)
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
    session.request_id = current_request_id()

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
                # Sheet/column structure + data issues, captured at upload. The model
                # has to commit a whole graph up front, so without this it can only
                # guess sheet names and columns — and guess wrong.
                "inspection": rec.inspection,
            }

    if not settings.MODEL_BASE_URL or not settings.MODEL_API_KEY or not settings.MODEL_NAME:
        raise ChatError("model_not_configured", "MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME 未配置")

    # The first message carries file context so the agent knows which file_ids are
    # valid; every message carries the current graph.
    session.messages.append({"role": "user", "content": _build_user_text(user_message, session)})
    _start_turn(session, store)

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

    segments: list[dict[str, Any]] = []
    tool_log_start = len(session.tool_calls_log)

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
        usage: dict[str, Any] = {}
        round_started = time.perf_counter()
        try:
            async for evt in caller(
                messages=session.messages,
                tools=agent_tool_definitions(),
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
                    usage = dict(evt.get("usage") or {})
            if stop_reason is None:
                raise ChatError("model_invalid_response", "模型未返回 stop_reason")
        except ChatError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise ChatError("model_error", f"模型调用失败: {exc}") from exc

        round_ms = int((time.perf_counter() - round_started) * 1000)
        _log_model_round(session, stop_reason, round_ms, content_blocks, usage)

        yield {"type": "model_response", "stop_reason": stop_reason}

        if stop_reason == "end_turn":
            text = _extract_text(content_blocks)
            if text:
                segments.append({"type": "text", "content": text})
            session.messages.append({"role": "assistant", "content": content_blocks})
            session.touch()
            _ui_append(session, "user", user_message)
            _ui_append(
                session,
                "assistant",
                text,
                tool_calls=session.tool_calls_log[tool_log_start:],
                segments=segments,
            )
            store.persist_messages(session)
            yield {
                "type": "done",
                "reply": text,
                "tool_calls": list(session.tool_calls_log),
                "output_name": _last_output_name(session),
                "sheets": list(session.tables.keys()),
                "segments": segments,
                "stage": session.stage,
                "graph": _public_graph(session.graph),
            }
            return

        if stop_reason == "max_tokens":
            text = _extract_text(content_blocks)
            if text:
                segments.append({"type": "text", "content": text})
            session.messages.append({"role": "assistant", "content": content_blocks})
            _ui_append(session, "user", user_message)
            _ui_append(
                session,
                "assistant",
                "模型输出过长，请简化需求",
                tool_calls=session.tool_calls_log[tool_log_start:],
                segments=segments,
            )
            store.persist_messages(session)
            yield {
                "type": "error",
                "code": "model_truncated",
                "message": "模型输出过长，请简化需求",
                "reply": "模型输出过长，请简化需求",
                "tool_calls": list(session.tool_calls_log),
                "output_name": _last_output_name(session),
                "sheets": list(session.tables.keys()),
                "segments": segments,
            }
            return

        if stop_reason == "tool_use":
            text = _extract_text(content_blocks)
            if text:
                segments.append({"type": "text", "content": text})
            session.messages.append({"role": "assistant", "content": content_blocks})
            tool_results: list[dict[str, Any]] = []
            submitted = False
            for block in content_blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_call = ToolCall(
                    tool_use_id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input") or {},
                )
                result, call_submitted = _handle_tool_call(session, tool_call)
                submitted = submitted or call_submitted

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.tool_use_id,
                        "content": truncate_result(result),
                    }
                )
                log_entry: dict[str, Any] = {
                    "tool": tool_call.name,
                    "status": "ok" if result.success else "error",
                    "summary": result.summary,
                }
                session.tool_calls_log.append(log_entry)
                segments.append({
                    "type": "tool",
                    "call": log_entry,
                    "output_name": log_entry.get("output_name"),
                })
                yield {
                    "type": "tool_end",
                    "id": tool_call.tool_use_id,
                    "name": tool_call.name,
                    "summary": result.summary,
                    "status": log_entry["status"],
                    "output_id": None,
                    "output_name": None,
                }
            session.messages.append({"role": "user", "content": tool_results})
            session.touch()
            if submitted:
                # The graph is in — persist it and stop. Nothing executes.
                store.persist_workflow(session)
                if not text:
                    text = "工作流图已生成，等待你批准。"
                    segments.append({"type": "text", "content": text})
                    yield {"type": "text", "delta": text}
                session.messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
                session.touch()
                _ui_append(
                    session,
                    "user",
                    user_message,
                )
                _ui_append(
                    session,
                    "assistant",
                    text,
                    tool_calls=session.tool_calls_log[tool_log_start:],
                    segments=segments,
                )
                store.persist_messages(session)
                yield {"type": "stage_change", "stage": session.stage}
                yield {
                    "type": "done",
                    "reply": text,
                    "tool_calls": list(session.tool_calls_log),
                    "output_name": _last_output_name(session),
                    "sheets": list(session.tables.keys()),
                    "segments": segments,
                    "stage": session.stage,
                    "graph": _public_graph(session.graph),
                }
                return
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
