"""Tests for tablex_decrypt handler + decrypt domain."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.app.mcp.handlers import handle_decrypt
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session


msoffcrypto = pytest.importorskip("msoffcrypto")


def _encrypt_xlsx(path: Path, password: str = "secret") -> Path:
    """Encrypt an xlsx in-memory and write to disk.

    Requires msoffcrypto-tool to encrypt from Python; if unavailable we skip.
    """
    from openpyxl import Workbook

    plain = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["name", "value"])
    ws.append(["x", 1])
    wb.save(plain)
    plain.seek(0)

    encrypted = io.BytesIO()
    office = msoffcrypto.OfficeFile(plain)
    office.load_key(password=password)
    # encrypt() is not always exposed by msoffcrypto-tool; fall back to
    # generating a file via msoffcrypto-tool CLI if needed.
    if not hasattr(office, "encrypt"):
        pytest.skip("msoffcrypto-tool 不支持 encrypt() 接口，跳过加密生成测试")
    office.encrypt(encrypted)
    encrypted.seek(0)
    path.write_bytes(encrypted.getvalue())
    return path


# ---------- domain tests rely on an unencrypted sample for code paths ----------


def test_decrypt_workbook_non_xlsx(tmp_path: Path) -> None:
    from backend.app.domain.decrypt import DecryptError, decrypt_workbook
    csv = tmp_path / "f.csv"
    csv.write_text("a,b\n1,2\n")
    with pytest.raises(DecryptError):
        decrypt_workbook(csv, "x")


def test_decrypt_workbook_missing_file(tmp_path: Path) -> None:
    from backend.app.domain.decrypt import DecryptError, decrypt_workbook
    with pytest.raises(DecryptError):
        decrypt_workbook(tmp_path / "missing.xlsx", "x")


def test_decrypt_workbook_not_encrypted(tmp_path: Path) -> None:
    """A plain xlsx should fail decryption with a clear error."""
    from openpyxl import Workbook
    from backend.app.domain.decrypt import DecryptError, decrypt_workbook

    plain = tmp_path / "plain.xlsx"
    wb = Workbook()
    wb.active.append(["a"])
    wb.save(plain)

    with pytest.raises(DecryptError):
        decrypt_workbook(plain, "wrong")


# ---------- handler ----------


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    s = Session("s", tmp_path / "out")
    return s


def test_handle_decrypt_missing_file(session: Session) -> None:
    res = handle_decrypt(
        ToolCall(
            tool_use_id="d1", name="tablex_decrypt",
            input={"file_id": "missing", "password": "x"},
        ),
        session,
    )
    assert not res.success


def test_handle_decrypt_missing_password(session: Session, tmp_path: Path) -> None:
    session.files["file-D"] = {"path": str(tmp_path / "x.xlsx"), "sha256": "x", "original_name": "x.xlsx"}
    res = handle_decrypt(
        ToolCall(
            tool_use_id="d1", name="tablex_decrypt",
            input={"file_id": "file-D", "password": ""},
        ),
        session,
    )
    assert not res.success
    assert "password" in (res.error or "")


def test_handle_decrypt_wrong_password(session: Session, tmp_path: Path) -> None:
    from openpyxl import Workbook
    plain = tmp_path / "plain.xlsx"
    Workbook().save(plain) if False else None  # silence unused
    wb = Workbook()
    wb.active.append(["a"])
    wb.save(plain)
    session.files["file-D"] = {"path": str(plain), "sha256": "x", "original_name": "plain.xlsx"}

    res = handle_decrypt(
        ToolCall(
            tool_use_id="d1", name="tablex_decrypt",
            input={"file_id": "file-D", "password": "wrong"},
        ),
        session,
    )
    assert not res.success
    assert "解密失败" in (res.summary or "")
