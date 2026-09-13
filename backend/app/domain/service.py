"""Workflow orchestration for the API."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import get_settings
from ..llm.demo import DemoPlanner
from ..llm.base import Planner
from ..schemas import (
    ExecutionResult,
    OperationPlan,
    SheetRef,
    WorkbookInspection,
)
from .executor import INTERNAL_COL, execute_plan
from .parser import (
    UnsupportedFileError,
    inspect_workbook,
    load_tables,
)


class ServiceError(RuntimeError):
    """Base class for service-layer errors."""

    def __init__(self, message: str):
        super().__init__(message)


class UnsupportedFileServiceError(ServiceError):
    pass


class AmbiguousRequestServiceError(ServiceError):
    pass


def _build_planner() -> Planner:
    settings = get_settings()
    if settings.APP_MODE == "llm":
        from ..llm.compatible import CompatiblePlanner
        try:
            return CompatiblePlanner(
                base_url=settings.MODEL_BASE_URL,
                api_key=settings.MODEL_API_KEY,
                model_name=settings.MODEL_NAME,
            )
        except Exception:
            return DemoPlanner()
    return DemoPlanner()


def _assign_file_ids(paths: Iterable[Path]) -> dict[Path, str]:
    mapping: dict[Path, str] = {}
    for path in paths:
        if path not in mapping:
            mapping[path] = uuid.uuid4().hex
    return mapping


def analyze_files(paths: list[Path]) -> list[WorkbookInspection]:
    inspections: list[WorkbookInspection] = []
    for path in paths:
        if not path.exists():
            raise ServiceError(f"文件不存在: {path}")
        try:
            inspections.append(inspect_workbook(path))
        except UnsupportedFileError as exc:
            raise UnsupportedFileServiceError(str(exc)) from exc
    return inspections


def _build_sheet_catalog(
    file_id_to_paths: dict[str, Path],
) -> list[SheetRef]:
    catalog: list[SheetRef] = []
    for file_id, path in file_id_to_paths.items():
        try:
            inspections = inspect_workbook(path)
        except UnsupportedFileError as exc:
            raise UnsupportedFileServiceError(str(exc)) from exc
        for sheet in inspections.sheets:
            catalog.append(
                SheetRef(
                    file_id=file_id,
                    sheet_name=sheet.name,
                    ref=f"{file_id}::{sheet.name}",
                ),
            )
    return catalog


def _build_tables(file_id_to_paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for file_id, path in file_id_to_paths.items():
        try:
            sheet_tables = load_tables(path)
        except UnsupportedFileError as exc:
            raise UnsupportedFileServiceError(str(exc)) from exc
        for sheet_name, df in sheet_tables.items():
            ref = f"{file_id}::{sheet_name}"
            tables[ref] = df
    return tables


def create_plan(
    file_id_to_paths: dict[str, Path],
    request: str,
) -> OperationPlan:
    catalog = _build_sheet_catalog(file_id_to_paths)
    inspections = [inspect_workbook(path) for path in file_id_to_paths.values()]
    planner = _build_planner()
    try:
        plan = planner.plan(request, inspections, catalog)
    except Exception as exc:
        raise AmbiguousRequestServiceError(str(exc)) from exc
    return plan


def run_plan(
    file_id_to_paths: dict[str, Path],
    plan: OperationPlan,
    confirmation_token: str | None,
    output_dir: Path,
) -> ExecutionResult:
    tables = _build_tables(file_id_to_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_id = uuid.uuid4().hex
    output_path = output_dir / f"{output_id}.xlsx"
    return execute_plan(tables, plan, confirmation_token, output_path)


def run_plan_with_tables(
    tables: dict[str, pd.DataFrame],
    plan: OperationPlan,
    confirmation_token: str | None,
    output_path: Path,
) -> ExecutionResult:
    return execute_plan(tables, plan, confirmation_token, output_path)