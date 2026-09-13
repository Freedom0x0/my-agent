from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.app.config import get_settings
from backend.app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "明细"
    sheet.append(["部门", "订单号", "金额"])
    sheet.append(["研发", "A001", "1,200"])
    sheet.append(["销售", "A002", "800"])
    source = tmp_path / "sample.xlsx"
    workbook.save(source)
    return source


def test_upload_plan_execute_and_download(client: TestClient, sample_file: Path) -> None:
    with sample_file.open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert upload.status_code == 201
    file_id = upload.json()["file_id"]
    assert upload.json()["inspection"]["sheets"]

    planned = client.post("/api/plans", json={"file_ids": [file_id], "request": "检查数据问题并按部门汇总金额"})
    assert planned.status_code == 200
    plan = planned.json()["plan"]

    executed = client.post(
        "/api/executions",
        json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"]},
    )
    assert executed.status_code == 201
    output_id = executed.json()["output_id"]

    audit = client.get(f"/api/outputs/{output_id}/audit")
    assert audit.status_code == 200
    assert audit.json()["events"]

    downloaded = client.get(f"/api/outputs/{output_id}")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/vnd.openxmlformats")


def test_execute_missing_confirmation_returns_409(client: TestClient, sample_file: Path) -> None:
    with sample_file.open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    file_id = upload.json()["file_id"]
    plan_resp = client.post("/api/plans", json={"file_ids": [file_id], "request": "按订单号去重并生成问题清单"})
    plan = plan_resp.json()["plan"]

    response = client.post("/api/executions", json={"file_ids": [file_id], "plan": plan, "confirmation_token": None})
    assert response.status_code == 409
    assert response.json()["error_code"] == "confirmation_required"


def test_upload_unsupported_extension(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "note.txt"
    bad.write_text("hello", encoding="utf-8")
    with bad.open("rb") as fh:
        response = client.post("/api/files", files={"file": ("note.txt", fh, "text/plain")})
    assert response.status_code == 400
    assert response.json()["error_code"] == "unsupported_file"


def test_plan_missing_file(client: TestClient) -> None:
    response = client.post("/api/plans", json={"file_ids": ["nope"], "request": "汇总"})
    assert response.status_code == 404


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_download_missing_output(client: TestClient) -> None:
    response = client.get("/api/outputs/missing")
    assert response.status_code == 404
    assert response.json()["error_code"] == "output_not_found"