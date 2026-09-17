"""Tests for TABLEX_TOOL_DEFINITIONS schema requirements."""
from __future__ import annotations

from backend.app.mcp.prompts import SYSTEM_PROMPT
from backend.app.mcp.tools import TABLEX_TOOL_DEFINITIONS


def _required(tool: dict) -> list[str]:
    return tool["input_schema"].get("required") or []


def test_export_requires_output_name() -> None:
    tool = next(t for t in TABLEX_TOOL_DEFINITIONS if t["name"] == "tablex_export")
    assert "output_name" in _required(tool)
    props = tool["input_schema"]["properties"]["output_name"]
    assert props["type"] == "string"
    assert props["minLength"] == 1
    assert props["maxLength"] == 100


def test_decrypt_requires_output_name() -> None:
    tool = next(t for t in TABLEX_TOOL_DEFINITIONS if t["name"] == "tablex_decrypt")
    assert "output_name" in _required(tool)


def test_export_styled_requires_output_name() -> None:
    tool = next(t for t in TABLEX_TOOL_DEFINITIONS if t["name"] == "tablex_export_styled")
    assert "output_name" in _required(tool)


def test_split_by_column_tool_definition() -> None:
    tool = next(t for t in TABLEX_TOOL_DEFINITIONS if t["name"] == "tablex_split_by_column")
    assert "output_name" in _required(tool)
    assert "group_column" in _required(tool)
    assert "file_id" in _required(tool)
    assert "sheet" in _required(tool)


def test_export_tool_does_not_mention_output_id() -> None:
    """output_id must not appear in tool descriptions — only output_name is the agent-visible name."""
    for tool in TABLEX_TOOL_DEFINITIONS:
        if tool["name"] in {"tablex_export", "tablex_export_styled", "tablex_decrypt"}:
            assert "output_id" not in (tool.get("description") or "")


def test_prompt_instructs_output_name() -> None:
    assert "output_name" in SYSTEM_PROMPT
    # Critical: AI is told not to repeat raw IDs back to the user.
    assert "output_id" in SYSTEM_PROMPT
    assert "不要" in SYSTEM_PROMPT  # explicit "do not" rule


def test_prompt_mentions_filter_output_sheet_rule() -> None:
    assert "output_sheet" in SYSTEM_PROMPT


def test_tool_descriptions_chinese() -> None:
    """All tool descriptions stay Chinese (no surprise language drift)."""
    for tool in TABLEX_TOOL_DEFINITIONS:
        for ch in tool["description"]:
            if "一" <= ch <= "鿿":
                # Has at least one CJK char.
                break
        else:
            raise AssertionError(f"{tool['name']} description lost Chinese")