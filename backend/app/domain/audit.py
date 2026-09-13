"""Audit helpers."""
from __future__ import annotations

import json
from typing import Any

from ..schemas import AuditEvent, Conclusion, ConclusionSource


def make_audit_event(
    *,
    step_id: str,
    operation: str,
    input_sheets: list[str],
    output_sheets: list[str],
    columns: list[str],
    input_rows: int,
    output_rows: int,
    affected_rows: list[int],
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        step_id=step_id,
        operation=operation,
        input_sheets=input_sheets,
        output_sheets=output_sheets,
        columns=columns,
        input_rows=input_rows,
        output_rows=output_rows,
        affected_rows=affected_rows[:200],
        details=details or {},
    )


def make_conclusion(
    *,
    text: str,
    source_step_id: str,
    sheet: str,
    value: Any = None,
    severity: str = "info",
    columns: list[str] | None = None,
    condition: str | None = None,
    formula: str | None = None,
    rows: list[int] | None = None,
) -> Conclusion:
    return Conclusion(
        text=text,
        value=value,
        severity=severity,
        source=ConclusionSource(
            step_id=source_step_id,
            sheet=sheet,
            columns=columns or [],
            condition=condition,
            formula=formula,
            rows=rows or [],
        ),
    )


def audit_events_to_rows(events: list[AuditEvent]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "step_id": event.step_id,
                "operation": event.operation,
                "input_sheets": ", ".join(event.input_sheets),
                "output_sheets": ", ".join(event.output_sheets),
                "columns": ", ".join(event.columns),
                "input_rows": event.input_rows,
                "output_rows": event.output_rows,
                "affected_rows": ", ".join(str(r) for r in event.affected_rows),
                "details_json": json.dumps(event.details, ensure_ascii=False),
            },
        )
    return rows