"""Tests for /api/sessions/{id} lazy-load support."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db import init_db, save_session_messages
from backend.app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    from backend.app.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime" / "metadata.db"
    init_db(path)
    return path


def _seed_messages(db_path: Path, session_id: str, n: int) -> None:
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(n)
    ]
    save_session_messages(db_path, session_id, messages)


def test_session_lazy_load_returns_latest_page(db_path: Path, client: TestClient) -> None:
    sid = "sess-lazy-1"
    _seed_messages(db_path, sid, 50)

    resp = client.get(f"/api/sessions/{sid}", params={"limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 50
    assert body["has_more"] is True
    assert body["oldest_index"] == 30
    assert len(body["messages"]) == 20
    assert body["messages"][0]["content"] == "msg-30"
    assert body["messages"][-1]["content"] == "msg-49"


def test_session_lazy_load_before_index_returns_older_page(
    db_path: Path, client: TestClient
) -> None:
    sid = "sess-lazy-2"
    _seed_messages(db_path, sid, 60)

    resp = client.get(
        f"/api/sessions/{sid}", params={"limit": 20, "before_index": 30}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 30
    assert body["has_more"] is True
    assert body["oldest_index"] == 10
    assert body["messages"][0]["content"] == "msg-10"
    assert body["messages"][-1]["content"] == "msg-29"


def test_session_lazy_load_terminates_when_no_more(
    db_path: Path, client: TestClient
) -> None:
    sid = "sess-lazy-3"
    _seed_messages(db_path, sid, 5)

    resp = client.get(f"/api/sessions/{sid}", params={"limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 5
    assert body["has_more"] is False
    assert body["oldest_index"] == 0
    assert len(body["messages"]) == 5


def test_session_no_limit_returns_all(db_path: Path, client: TestClient) -> None:
    sid = "sess-lazy-4"
    _seed_messages(db_path, sid, 12)

    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 12
    assert body["has_more"] is False
    assert body["oldest_index"] == 0
    assert len(body["messages"]) == 12


def test_session_not_found(client: TestClient) -> None:
    resp = client.get("/api/sessions/does-not-exist", params={"limit": 5})
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "session_not_found"


# --- UI transcript (ui_messages_json) -------------------------------------------


def test_ui_transcript_is_returned_verbatim(db_path: Path, client: TestClient) -> None:
    """The interleaved timeline is stored as-is, so a reload renders the same shape."""
    sid = "sess-ui-1"
    save_session_messages(
        db_path,
        sid,
        [{"role": "user", "content": "处理一下"}],
        ui_messages=[
            {"role": "user", "content": "处理一下", "tool_calls": [], "segments": []},
            {
                "role": "assistant",
                "content": "改好了",
                "tool_calls": [{"tool": "tablex_fill_null", "status": "ok", "summary": "填充 12 个空值"}],
                "segments": [
                    {"type": "text", "content": "先看一下"},
                    {
                        "type": "tool",
                        "call": {"tool": "tablex_fill_null", "status": "ok", "summary": "填充 12 个空值"},
                        "output_name": "清洗后数据",
                    },
                    {"type": "text", "content": "改好了"},
                ],
            },
        ],
    )

    body = client.get(f"/api/sessions/{sid}").json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "处理一下"
    assert [s["type"] for s in body["messages"][1]["segments"]] == ["text", "tool", "text"]
    assert body["messages"][1]["segments"][1]["output_name"] == "清洗后数据"


def test_legacy_row_without_ui_transcript_falls_back_to_text(
    db_path: Path, client: TestClient,
) -> None:
    """Rows written before ui_messages_json existed still render — text only."""
    sid = "sess-ui-2"
    save_session_messages(db_path, sid, [
        {"role": "user", "content": "老会话"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "回答"}],
        },
        # Synthetic tool round-trip: must NOT come back as an empty user bubble.
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "{}"}]},
    ])

    body = client.get(f"/api/sessions/{sid}").json()
    assert [m["content"] for m in body["messages"]] == ["老会话", "回答"]
    assert all(m["segments"] == [] for m in body["messages"])

# --- Session-scoped files -------------------------------------------------------


def _sample_xlsx(tmp_path: Path) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["部门", "金额"])
    ws.append(["研发", "1200"])
    src = tmp_path / "sample.xlsx"
    wb.save(src)
    return src


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_uploaded_file_comes_back_with_its_session(
    db_path: Path, client: TestClient, tmp_path: Path,
) -> None:
    sid = "sess-files-1"
    with _sample_xlsx(tmp_path).open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, XLSX_MIME)},
            data={"session_id": sid},
        )
    assert upload.status_code == 201
    file_id = upload.json()["file_id"]

    body = client.get(f"/api/sessions/{sid}").json()
    assert [f["file_id"] for f in body["files"]] == [file_id]
    assert body["files"][0]["filename"] == "sample.xlsx"
    assert body["files"][0]["inspection"]["sheets"]


def test_file_content_endpoint_returns_original_bytes(
    db_path: Path, client: TestClient, tmp_path: Path,
) -> None:
    source = _sample_xlsx(tmp_path)
    with source.open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, XLSX_MIME)},
            data={"session_id": "sess-files-2"},
        )
    file_id = upload.json()["file_id"]

    resp = client.get(f"/api/files/{file_id}/content")
    assert resp.status_code == 200
    assert resp.content == source.read_bytes()


def test_file_content_unknown_id_is_404(client: TestClient) -> None:
    assert client.get("/api/files/nope/content").status_code == 404


def test_upload_without_session_belongs_to_no_session(
    db_path: Path, client: TestClient, tmp_path: Path,
) -> None:
    """A session with neither messages nor files simply doesn't exist."""
    with _sample_xlsx(tmp_path).open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, XLSX_MIME)},
        )
    assert upload.status_code == 201

    assert client.get("/api/sessions/sess-files-3").status_code == 404


def test_files_are_listed_before_the_first_message(
    db_path: Path, client: TestClient, tmp_path: Path,
) -> None:
    """Upload happens before the first chat turn, so there's no sessions row yet."""
    sid = "sess-files-4"
    with _sample_xlsx(tmp_path).open("rb") as fh:
        upload = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, XLSX_MIME)},
            data={"session_id": sid},
        )
    file_id = upload.json()["file_id"]

    body = client.get(f"/api/sessions/{sid}").json()
    assert body["messages"] == []
    assert [f["file_id"] for f in body["files"]] == [file_id]
