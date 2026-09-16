"""OpenAI / Anthropic compatible planner."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ...schemas import OperationPlan, SheetRef, WorkbookInspection


class ModelConfigError(RuntimeError):
    """Raised when MODEL_* settings are incomplete."""


class ModelTimeout(RuntimeError):
    """Raised when the model request times out."""


class ModelInvalidResponse(RuntimeError):
    """Raised when the model response cannot be parsed."""


SCHEMA_DESCRIPTION = """You are a planning assistant. Output EXACTLY ONE JSON object matching this schema (no markdown, no prose, no code fences):

{
  "id": "plan-<random>",
  "source_sheets": ["<file_id>::<sheet_name>", ...],
  "operations": [
    {"kind": "normalize", "sheet": "<file_id>::<sheet_name>", "columns": ["<col>"], "target_type": "number"|"date"|"text"}
    or {"kind": "deduplicate", "sheet": "<file_id>::<sheet_name>", "key_columns": ["..."], "keep": "first"|"last"}
    or {"kind": "filter", "sheet": "<file_id>::<sheet_name>", "conditions": [{"column":"...","operator":"eq|ne|contains|gt|gte|lt|lte|is_null|not_null|in","value":...}], "match": "all"|"any", "output_sheet": "..."}
    or {"kind": "group_summary", "sheet": "<file_id>::<sheet_name>", "group_by": ["..."], "metrics": {"<col>": ["sum"|"mean"|"count"|"min"|"max"]}, "output_sheet": "..."}
    or {"kind": "compare", "left_sheet": "<file_id>::<sheet_name>", "right_sheet": "<file_id>::<sheet_name>", "key_columns": ["..."], "output_sheet": "..."}
    or {"kind": "fill_formula", "sheet": "<file_id>::<sheet_name>", "target_column": "...", "expression": "...", "start_row": 2, "end_row": 100, "only_blank": true}
    or {"kind": "create_issue_sheet", "output_sheet": "问题清单"}
  ],
  "outputs": ["清洗后数据", "<operation_output_sheet>", "问题清单"],
  "explanation": "<one sentence in Chinese>",
  "requires_confirmation": true,
  "clarification_question": null
}

Rules:
- Every "sheet", "left_sheet", "right_sheet" MUST be a SheetRef of the form "<file_id>::<sheet_name>" and MUST equal one of the entries in source_sheets.
- For compare, BOTH left_sheet and right_sheet MUST come from source_sheets. You may NOT reference an operation output as compare input.
- "outputs" MUST list "清洗后数据" when normalize or deduplicate is present, plus every output_sheet declared by an operation.
- "requires_confirmation" MUST be true when deduplicate or fill_formula is present, otherwise false.
- Use ONLY sheets and columns that appear in the inspection payload.
- Do NOT output Python code, paths, or computed numbers.
- If uncertain, set clarification_question to a short Chinese question and leave operations empty.
"""


def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float, bool)):
        return [value]
    return list(value)


def _normalize_plan_dict(plan_dict: dict) -> dict:
    """Tolerate common model deviations before strict validation."""
    for op in plan_dict.get("operations") or []:
        if not isinstance(op, dict):
            continue
        kind = op.get("kind")
        if kind == "normalize" and "columns" in op:
            op["columns"] = _coerce_list(op["columns"])
        elif kind == "deduplicate" and "key_columns" in op:
            op["key_columns"] = _coerce_list(op["key_columns"])
        elif kind == "filter":
            if "conditions" in op:
                op["conditions"] = _coerce_list(op["conditions"])
        elif kind == "group_summary":
            if "group_by" in op:
                op["group_by"] = _coerce_list(op["group_by"])
            if isinstance(op.get("metrics"), dict):
                op["metrics"] = {k: _coerce_list(v) for k, v in op["metrics"].items()}
        elif kind == "compare" and "key_columns" in op:
            op["key_columns"] = _coerce_list(op["key_columns"])
        if "source_sheets" not in plan_dict and kind in {"compare"}:
            pass
        # fill_formula: start_row/end_row may be strings
        if kind == "fill_formula":
            for field in ("start_row", "end_row"):
                if field in op:
                    try:
                        op[field] = int(op[field])
                    except (TypeError, ValueError):
                        pass
    if "outputs" in plan_dict:
        plan_dict["outputs"] = _coerce_list(plan_dict["outputs"])
    if "source_sheets" in plan_dict:
        plan_dict["source_sheets"] = _coerce_list(plan_dict["source_sheets"])
    source_set = set(plan_dict.get("source_sheets") or [])
    # Strip compare operations referencing non-source sheets
    if source_set:
        filtered_ops = []
        for op in plan_dict.get("operations") or []:
            if not isinstance(op, dict):
                continue
            if op.get("kind") == "compare":
                left = op.get("left_sheet", "")
                right = op.get("right_sheet", "")
                if left not in source_set or right not in source_set:
                    continue  # skip compare that references an output, not a source
            filtered_ops.append(op)
        plan_dict["operations"] = filtered_ops
    # Ensure requires_confirmation is set when high-impact ops are present
    high_impact = {"deduplicate", "fill_formula"}
    if any(isinstance(op, dict) and op.get("kind") in high_impact for op in plan_dict.get("operations") or []):
        plan_dict["requires_confirmation"] = True
    return plan_dict


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _detect_style(base_url: str, configured: str) -> str:
    if configured in {"openai", "anthropic"}:
        return configured
    lowered = base_url.lower()
    if lowered.endswith("/anthropic") or "/anthropic" in lowered:
        return "anthropic"
    return "openai"


class CompatiblePlanner:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        api_style: str = "auto",
        timeout_seconds: float = 60.0,
    ):
        if not base_url or not api_key or not model_name:
            raise ModelConfigError("MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME 未配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.api_style = _detect_style(base_url, api_style)
        self.timeout_seconds = timeout_seconds

    def plan(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        if self.api_style == "anthropic":
            return self._plan_anthropic(request, inspections, sheet_catalog)
        return self._plan_openai(request, inspections, sheet_catalog)

    def _plan_openai(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SCHEMA_DESCRIPTION},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request,
                            "sheets": [ref.model_dump() for ref in sheet_catalog],
                            "inspections": [insp.model_dump() for insp in inspections],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeout("模型请求超时") from exc
        except httpx.HTTPError as exc:
            raise ModelInvalidResponse(f"模型请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise ModelInvalidResponse(
                f"模型返回错误 {response.status_code}: {response.text[:200]}",
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            plan_dict = json.loads(content) if isinstance(content, str) else content
            plan_dict = _normalize_plan_dict(plan_dict)
            return OperationPlan.model_validate(plan_dict)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ModelInvalidResponse(f"模型响应无法解析: {exc}") from exc

    def _plan_anthropic(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        user_payload = json.dumps(
            {
                "request": request,
                "sheets": [ref.model_dump() for ref in sheet_catalog],
                "inspections": [insp.model_dump() for insp in inspections],
            },
            ensure_ascii=False,
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "system": SCHEMA_DESCRIPTION,
            "messages": [{"role": "user", "content": user_payload}],
            "max_tokens": 4096,
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeout("模型请求超时") from exc
        except httpx.HTTPError as exc:
            raise ModelInvalidResponse(f"模型请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise ModelInvalidResponse(
                f"模型返回错误 {response.status_code}: {response.text[:200]}",
            )

        try:
            data = response.json()
            blocks = data.get("content") or []
            text_parts = [
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = _strip_code_fence("\n".join(text_parts))
            try:
                plan_dict = json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if start < 0 or end <= start:
                    raise ModelInvalidResponse("模型响应未包含 JSON")
                plan_dict = json.loads(content[start : end + 1])
            plan_dict = _normalize_plan_dict(plan_dict)
            return OperationPlan.model_validate(plan_dict)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ModelInvalidResponse(f"模型响应无法解析: {exc}") from exc