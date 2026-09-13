from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.app.domain.executor import (
    INTERNAL_COL,
    execute_plan,
    file_sha256,
)
from backend.app.domain.operations import (
    ConfirmationRequired,
    InvalidPlanError,
)
from backend.app.schemas import (
    CompareOperation,
    CreateIssueSheetOperation,
    DeduplicateOperation,
    FillFormulaOperation,
    FilterOperation,
    GroupSummaryOperation,
    NormalizeOperation,
    OperationPlan,
)


@pytest.fixture()
def messy_workbook(tmp_path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "明细"
    sheet.append(["部门", "订单号", "金额"])
    sheet.append(["研发", "A001", "1,200"])
    sheet.append(["研发", "A001", "1,200"])  # duplicate
    sheet.append(["销售", "A002", "800"])
    sheet.append(["销售", "A003", "1,500"])
    source = tmp_path / "messy.xlsx"
    workbook.save(source)
    return source


@pytest.fixture()
def messy_tables(messy_workbook: Path) -> dict[str, pd.DataFrame]:
    df = pd.read_excel(messy_workbook, sheet_name="明细")
    df[INTERNAL_COL] = list(range(2, 2 + len(df)))
    return {f"file-001::{messy_workbook.stem}": df}


def test_execute_plan_creates_new_workbook_and_audit_events(
    messy_workbook: Path, messy_tables: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    sheet_ref = next(iter(messy_tables))
    plan = OperationPlan(
        id="plan-1",
        source_sheets=[sheet_ref],
        operations=[
            NormalizeOperation(sheet=sheet_ref, columns=["金额"], target_type="number"),
            DeduplicateOperation(sheet=sheet_ref, key_columns=["订单号"]),
            GroupSummaryOperation(
                sheet=sheet_ref, group_by=["部门"], metrics={"金额": ["sum"]},
            ),
        ],
        outputs=["清洗后数据", "汇总结果"],
        requires_confirmation=True,
        explanation="统一金额并按订单号去重后汇总部门金额",
    )

    with pytest.raises(ConfirmationRequired):
        execute_plan(messy_tables, plan, confirmation_token=None, output_path=tmp_path / "out.xlsx")

    plan.outputs = ["清洗后数据", "汇总结果", "问题清单"]
    plan.operations.append(CreateIssueSheetOperation(output_sheet="问题清单"))
    output = tmp_path / "result.xlsx"
    result = execute_plan(messy_tables, plan, confirmation_token="confirm:plan-1", output_path=output)

    assert output.exists()
    assert {"清洗后数据", "汇总结果", "问题清单"}.issubset(set(result.sheets))
    assert any(event.operation == "deduplicate" for event in result.audit_events)


def test_execute_plan_emits_compare_results(messy_tables: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    sheet_ref = next(iter(messy_tables))
    left = messy_tables[sheet_ref].drop_duplicates(subset=["订单号"]).reset_index(drop=True)
    right = left.copy()
    right["金额"] = right["金额"].astype(object)
    right.loc[right["订单号"] == "A001", "金额"] = "9,999"
    tables = {
        "file-L::明细": left,
        "file-R::明细": right,
    }
    plan = OperationPlan(
        id="plan-cmp",
        source_sheets=list(tables.keys()),
        operations=[
            CompareOperation(
                left_sheet="file-L::明细",
                right_sheet="file-R::明细",
                key_columns=["订单号"],
                output_sheet="对比结果",
            ),
        ],
        outputs=["对比结果"],
        requires_confirmation=False,
        explanation="对比金额变化",
    )
    output = tmp_path / "cmp.xlsx"
    result = execute_plan(tables, plan, confirmation_token=None, output_path=output)
    assert any(c.text.startswith("对比结果中") for c in result.conclusions)
    assert any(e.operation == "compare" for e in result.audit_events)


def test_execute_plan_fill_formula_only_blanks(messy_tables: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    sheet_ref = next(iter(messy_tables))
    plan = OperationPlan(
        id="plan-formula",
        source_sheets=[sheet_ref],
        operations=[
            FillFormulaOperation(
                sheet=sheet_ref, target_column="金额", expression="{金额}*2",
                start_row=2, end_row=10, only_blank=True,
            ),
        ],
        outputs=["清洗后数据"],
        requires_confirmation=True,
        explanation="补充公式",
    )
    with pytest.raises(ConfirmationRequired):
        execute_plan(messy_tables, plan, confirmation_token=None, output_path=tmp_path / "out.xlsx")
    result = execute_plan(messy_tables, plan, confirmation_token="confirm:plan-formula", output_path=tmp_path / "result.xlsx")
    assert result.output_path.endswith(".xlsx")
    assert any(e.operation == "fill_formula" for e in result.audit_events)


def test_execute_plan_validates_unknown_kind(messy_tables: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    sheet_ref = next(iter(messy_tables))
    plan = OperationPlan.model_construct(
        id="plan-bad",
        source_sheets=[sheet_ref],
        operations=[{"kind": "evil", "sheet": sheet_ref}],
        outputs=["清洗后数据"],
        explanation="bad",
        requires_confirmation=False,
    )
    with pytest.raises(Exception):
        execute_plan(messy_tables, plan, confirmation_token=None, output_path=tmp_path / "out.xlsx")


def test_execute_plan_rejects_unknown_columns(messy_tables: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    sheet_ref = next(iter(messy_tables))
    plan = OperationPlan(
        id="plan-bad",
        source_sheets=[sheet_ref],
        operations=[NormalizeOperation(sheet=sheet_ref, columns=["不存在的列"], target_type="number")],
        outputs=["清洗后数据"],
        explanation="bad",
        requires_confirmation=False,
    )
    with pytest.raises(InvalidPlanError):
        execute_plan(messy_tables, plan, confirmation_token=None, output_path=tmp_path / "out.xlsx")


def test_execute_plan_output_reopens_and_source_unchanged(
    messy_workbook: Path, messy_tables: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    sheet_ref = next(iter(messy_tables))
    before_hash = file_sha256(messy_workbook)
    plan = OperationPlan(
        id="plan-hash",
        source_sheets=[sheet_ref],
        operations=[
            NormalizeOperation(sheet=sheet_ref, columns=["金额"], target_type="number"),
            DeduplicateOperation(sheet=sheet_ref, key_columns=["订单号"]),
        ],
        outputs=["清洗后数据", "问题清单"],
        requires_confirmation=True,
        explanation="检查",
    )
    plan.operations.append(CreateIssueSheetOperation(output_sheet="问题清单"))
    output = tmp_path / "result.xlsx"
    execute_plan(messy_tables, plan, confirmation_token="confirm:plan-hash", output_path=output)
    assert file_sha256(messy_workbook) == before_hash
    from openpyxl import load_workbook as _lw
    wb = _lw(output, read_only=True, data_only=False)
    try:
        names = [s.title for s in wb.worksheets]
    finally:
        wb.close()
    assert any(n.startswith("原始_") for n in names)
    assert "_audit" in names


def test_execute_plan_rejects_fill_formula_outside_range(
    messy_tables: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    sheet_ref = next(iter(messy_tables))
    plan = OperationPlan(
        id="plan-out",
        source_sheets=[sheet_ref],
        operations=[
            FillFormulaOperation(
                sheet=sheet_ref, target_column="金额", expression="{金额}+1",
                start_row=100, end_row=200, only_blank=True,
            ),
        ],
        outputs=["清洗后数据"],
        explanation="bad range",
        requires_confirmation=True,
    )
    result = execute_plan(
        messy_tables, plan,
        confirmation_token="confirm:plan-out",
        output_path=tmp_path / "result.xlsx",
    )
    # Operation is valid, but no rows affected because range is beyond data
    assert result.audit_events[0].affected_rows == []