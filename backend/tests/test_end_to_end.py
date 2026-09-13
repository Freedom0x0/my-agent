from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.domain.parser import INTERNAL_COL
from backend.app.domain.executor import file_sha256
from backend.app.main import create_app


@pytest.fixture()
def fixture_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


def _upload(client: TestClient, path: Path) -> str:
    with path.open("rb") as fh:
        resp = client.post(
            "/api/files",
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["file_id"]


def _read_output(path: Path) -> dict[str, pd.DataFrame]:
    sheets: dict[str, pd.DataFrame] = pd.read_excel(path, sheet_name=None)
    return sheets


def _audit_sheet_state(path: Path) -> dict[str, str]:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=False)
    try:
        return {s.title: s.sheet_state for s in wb.worksheets}
    finally:
        wb.close()


def test_primary_demo_prompt_produces_audited_download(client: TestClient, fixture_dir: Path) -> None:
    source = fixture_dir / "expenses_and_budget.xlsx"
    file_id = _upload(client, source)
    request_text = "检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。"

    plan_resp = client.post("/api/plans", json={"file_ids": [file_id], "request": request_text})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()["plan"]
    kinds = [op["kind"] for op in plan["operations"]]
    assert {"normalize", "deduplicate", "group_summary", "create_issue_sheet"}.issubset(set(kinds))
    assert plan["requires_confirmation"] is True

    before_hash = file_sha256(source)
    no_confirm = client.post(
        "/api/executions",
        json={"file_ids": [file_id], "plan": plan, "confirmation_token": None},
    )
    assert no_confirm.status_code == 409
    assert no_confirm.json()["error_code"] == "confirmation_required"

    response = client.post(
        "/api/executions",
        json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    output_id = body["output_id"]
    assert body["conclusions"], "应当至少有一个结论"
    assert "问题清单" in body["sheets"], "输出应包含问题清单工作表"

    audit = client.get(f"/api/outputs/{output_id}/audit")
    assert audit.status_code == 200
    step_ids = {event["step_id"] for event in audit.json()["events"]}
    assert any(c["source"]["step_id"] in step_ids for c in body["conclusions"]), \
        "结论应当引用真实审计 step_id"

    download = client.get(f"/api/outputs/{output_id}")
    assert download.status_code == 200
    out_path = tmp_path_factory_for_download(client) / "result.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(download.content)

    sheets = _read_output(out_path)
    assert "问题清单" in sheets
    sheet_states = _audit_sheet_state(out_path)
    assert "_audit" in sheet_states
    assert sheet_states["_audit"] == "hidden", "_audit 工作表应被隐藏"
    assert file_sha256(source) == before_hash, "源文件应未被修改"


def tmp_path_factory_for_download(client: TestClient) -> Path:
    settings = get_settings()
    return Path(settings.APP_DATA_DIR) / "outputs"


def test_dedup_path_on_personnel_fixture(client: TestClient, fixture_dir: Path) -> None:
    source = fixture_dir / "personnel_messy.xlsx"
    file_id = _upload(client, source)
    plan_resp = client.post("/api/plans", json={"file_ids": [file_id], "request": "按证件号去重并生成问题清单"})
    plan = plan_resp.json()["plan"]
    response = client.post(
        "/api/executions",
        json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"]},
    )
    assert response.status_code == 201, response.text


def test_status_filter_path_on_project_fixture(client: TestClient, fixture_dir: Path) -> None:
    source = fixture_dir / "project_progress_messy.xlsx"
    file_id = _upload(client, source)
    plan_resp = client.post("/api/plans", json={"file_ids": [file_id], "request": "筛选状态为进行中的项目"})
    plan = plan_resp.json()["plan"]
    response = client.post(
        "/api/executions",
        json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"] if plan["requires_confirmation"] else None},
    )
    assert response.status_code in (201, 409)
    if response.status_code == 409:
        # confirm and retry
        response = client.post(
            "/api/executions",
            json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"]},
        )
        assert response.status_code == 201, response.text