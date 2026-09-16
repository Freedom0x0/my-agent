"""Decrypt encrypted .xlsx workbooks using msoffcrypto-tool.

ponytail: only .xlsx is supported; .xls uses a different crypto scheme
not handled by msoffcrypto-tool. Upgrade path: add olefile-based RC4
decryption for legacy .xls if needed.
"""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pandas as pd


class DecryptError(ValueError):
    """Raised when decryption fails (wrong password, non-encrypted file, etc.)."""


def decrypt_workbook(path: Path, password: str) -> dict[str, pd.DataFrame]:
    """Decrypt an encrypted .xlsx file and return its sheets as DataFrames.

    Raises DecryptError if the password is wrong or the file is not encrypted.
    """
    try:
        import msoffcrypto
    except ImportError as exc:
        raise DecryptError("缺少 msoffcrypto-tool 依赖，无法解密加密文件") from exc

    if not path.exists():
        raise DecryptError(f"文件不存在: {path}")
    if path.suffix.lower() != ".xlsx":
        raise DecryptError("目前仅支持 .xlsx 格式的解密")

    decrypted = io.BytesIO()
    try:
        with open(path, "rb") as f:
            office_file = msoffcrypto.OfficeFile(f)
            office_file.load_key(password=password)
            office_file.decrypt(decrypted)
    except Exception as exc:
        # msoffcrypto raises a few different errors depending on the case
        # (InvalidKeyError, UnsupportedError, etc.); collapse to a single
        # domain error so the handler can map it to _fail().
        raise DecryptError(f"解密失败: {exc}") from exc

    decrypted.seek(0)
    wb = openpyxl.load_workbook(decrypted, data_only=True, read_only=True)
    try:
        sheets: dict[str, pd.DataFrame] = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            sheets[sheet_name] = _rows_to_df(rows)
    finally:
        wb.close()
    return sheets


def _rows_to_df(rows: list[list]) -> pd.DataFrame:
    """Convert openpyxl rows to DataFrame, mirroring the parser's normalisation."""
    if not rows:
        return pd.DataFrame()
    # Find first non-empty row as header
    header_idx = 0
    for i, row in enumerate(rows[:20]):
        if any(c is not None and str(c).strip() != "" for c in row):
            header_idx = i
            break
    else:
        return pd.DataFrame()

    raw_header = rows[header_idx]
    used: set[str] = set()
    columns: list[str] = []
    for cell in raw_header:
        base = str(cell).strip() if cell is not None else ""
        if not base:
            base = "列"
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        used.add(candidate)
        columns.append(candidate)

    body = [r for r in rows[header_idx + 1:] if any(c is not None and str(c).strip() != "" for c in r)]
    if not body:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(body, columns=columns).astype(object).where(
        pd.DataFrame(body, columns=columns).notna(), None,
    )
    return df.reset_index(drop=True)
