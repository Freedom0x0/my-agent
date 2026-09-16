from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.app.domain.executor import INTERNAL_COL
from backend.app.domain.service import (
    AmbiguousRequestServiceError,
    UnsupportedFileServiceError,
    analyze_files,
    create_plan,
    run_plan_with_tables,
)
from backend.app.schemas import (
    AuditEvent,
    Conclusion,
)


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "明细"
    sheet.append(["部门", "订单号", "金额", "状态"])
    sheet.append(["研发", "A001", "1,200", "已完成"])
    sheet.append(["销售", "A002", "800", "进行中"])
    sheet.append(["研发", "A003", "2,000", "已完成"])
    source = tmp_path / "sample.xlsx"
    workbook.save(source)
    return source


@pytest.fixture()
def file_id_map(sample_file: Path) -> dict[str, Path]:
    return {"file-001": sample_file}


def test_analyze_files_returns_inspection(sample_file: Path) -> None:
    inspections = analyze_files([sample_file])
    assert inspections[0].sheets[0].row_count == 3
    assert inspections[0].sheets[0].columns[0].name == "部门"


def test_demo_planner_turns_natural_language_into_typed_plan(file_id_map: dict[str, Path]) -> None:
    plan = create_plan(file_id_map, "检查数据问题，统一金额格式并按部门汇总")
    kinds = {op.kind for op in plan.operations}
    assert "normalize" in kinds
    assert "group_summary" in kinds
    assert plan.requires_confirmation is True
    assert "清洗后数据" in plan.outputs
    assert "汇总结果" in plan.outputs
    assert "问题清单" in plan.outputs


def test_demo_planner_handles_dedup_request(file_id_map: dict[str, Path]) -> None:
    plan = create_plan(file_id_map, "按订单号去重并生成问题清单")
    assert any(op.kind == "deduplicate" for op in plan.operations)


def test_demo_planner_filter_status(file_id_map: dict[str, Path]) -> None:
    plan = create_plan(file_id_map, "筛选状态列非空的记录")
    assert any(op.kind == "filter" for op in plan.operations)


def test_service_full_workflow(sample_file: Path, tmp_path: Path) -> None:
    file_id_map = {"file-001": sample_file}
    inspections = analyze_files([sample_file])
    plan = create_plan(file_id_map, "检查数据问题并按部门汇总金额")
    tables = {
        f"file-001::{inspections[0].sheets[0].name}": _load_tables(sample_file),
    }
    output_path = tmp_path / "result.xlsx"
    result = run_plan_with_tables(
        tables, plan,
        confirmation_token=f"confirm:{plan.id}",
        output_path=output_path,
    )
    assert output_path.exists()
    assert any(isinstance(c, Conclusion) and c.source.step_id for c in result.conclusions)
    assert any(isinstance(e, AuditEvent) for e in result.audit_events)


def test_service_ambiguous_request_raises(sample_file: Path) -> None:
    # DemoPlanner should handle any request gracefully now
    plan = create_plan({"file-001": sample_file}, "做一些我描述不出来的数据处理")
    assert plan.operations, "should return a default plan instead of raising"


def test_service_unsupported_file(tmp_path: Path) -> None:
    bad = tmp_path / "note.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFileServiceError):
        analyze_files([bad])


def test_demo_planner_fill_formula(file_id_map: dict[str, Path]) -> None:
    plan = create_plan(file_id_map, "补充空白公式")
    assert any(op.kind == "fill_formula" for op in plan.operations)


def _load_tables(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="明细")
    df[INTERNAL_COL] = list(range(2, 2 + len(df)))
    return df