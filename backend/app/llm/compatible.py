"""OpenAI-compatible planner."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..schemas import OperationPlan, SheetRef, WorkbookInspection


class ModelConfigError(RuntimeError):
    """Raised when MODEL_* settings are incomplete."""


class ModelTimeout(RuntimeError):
    """Raised when the model request times out."""


class ModelInvalidResponse(RuntimeError):
    """Raised when the model response cannot be parsed."""


SCHEMA_DESCRIPTION = """Return ONLY a JSON object matching the OperationPlan schema.

Available operation kinds:
- normalize: { sheet, columns: list[str], target_type: "number"|"date"|"text" }
- deduplicate: { sheet, key_columns: list[str], keep: "first"|"last" }
- filter: { sheet, conditions: [...], match: "all"|"any", output_sheet }
- group_summary: { sheet, group_by: list[str], metrics: {col: [funcs]}, output_sheet }
- compare: { left_sheet, right_sheet, key_columns: list[str], output_sheet }
- fill_formula: { sheet, target_column, expression, start_row, end_row, only_blank }
- create_issue_sheet: { output_sheet }

Rules:
- Use only sheets and columns that appear in the inspection.
- Use SheetRef format "<file_id>::<sheet_name>" for sheet references.
- Do NOT output Python code, paths, or computed numeric values.
- If you cannot determine the fields, return clarification_question instead of guessing.
"""


class CompatiblePlanner:
    def __init__(self, base_url: str, api_key: str, model_name: str, timeout_seconds: float = 30.0):
        if not base_url or not api_key or not model_name:
            raise ModelConfigError("MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME 未配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def plan(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SCHEMA_DESCRIPTION},
                {"role": "user", "content": json.dumps(
                    {
                        "request": request,
                        "sheets": [ref.model_dump() for ref in sheet_catalog],
                        "inspections": [insp.model_dump() for insp in inspections],
                    },
                    ensure_ascii=False,
                )},
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
            raise ModelInvalidResponse(f"模型返回错误 {response.status_code}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            plan_dict = json.loads(content)
            return OperationPlan.model_validate(plan_dict)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ModelInvalidResponse("模型响应无法解析") from exc