"""Workbook parsing and table-health inspection.

Public API re-exported from internal modules for backwards compatibility
with `from backend.app.domain.parser import inspect_workbook, load_tables, ...`.
"""
from __future__ import annotations

from ._excel import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileError,
    inspect_workbook,
    is_supported_file,
    load_tables,
)
from ._metadata import (
    HEADER_SCAN_LIMIT,
    INTERNAL_COL,
    INTERNAL_SOURCE_ROW,
    MAX_PREVIEW_ROWS,
    RESERVED_PREFIX,
)
from ._validate import MAX_AFFECTED_ROWS_LOG

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "UnsupportedFileError",
    "inspect_workbook",
    "load_tables",
    "is_supported_file",
    "RESERVED_PREFIX",
    "INTERNAL_COL",
    "INTERNAL_SOURCE_ROW",
    "MAX_PREVIEW_ROWS",
    "HEADER_SCAN_LIMIT",
    "MAX_AFFECTED_ROWS_LOG",
]
