"""Planner protocol."""
from __future__ import annotations

from typing import Protocol

from ..schemas import OperationPlan, SheetRef, WorkbookInspection


class Planner(Protocol):
    def plan(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        ...