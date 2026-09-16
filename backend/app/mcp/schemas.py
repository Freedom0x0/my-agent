"""Pydantic models for the MCP anti-corruption layer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Maximum bytes for a single tool_result string (anti-token-bomb).
MAX_RESULT_BYTES = 4000
# Maximum tool calls per user message.
MAX_TOOL_CALLS = 15
# Maximum seconds for a single tool handler.
MAX_TOOL_CALL_SECONDS = 120
# Maximum seconds for a MiniMax API call.
MAX_MODEL_SECONDS = 120


class ToolCall(BaseModel):
    """A tool invocation request from the model."""

    tool_use_id: str
    name: str
    input: dict[str, Any]


class ToolResult(BaseModel):
    """Structured result returned to the model."""

    success: bool = True
    summary: str = ""
    data: dict[str, Any] | None = None
    error: str | None = None


class ValidationResult(BaseModel):
    """Outcome of pre-handler input validation."""

    ok: bool = True
    error: str | None = None


class ToolCallLog(BaseModel):
    """One entry in the session's tool call log."""

    tool: str
    status: str  # "ok" | "error"
    summary: str
    output_id: str | None = None