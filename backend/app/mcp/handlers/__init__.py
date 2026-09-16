"""Auto-discovered tablex tool handlers.

Each per-tool module under this package exposes a module-level `HANDLERS`
dict mapping tool name → `HandlerSpec`. This package re-aggregates them via
`pkgutil.iter_modules`, then exposes the merged dict (sorted by tool name for
deterministic ordering) as `HANDLERS` at package level so existing callers
(`from .handlers import HANDLERS, truncate_result, validate_tool_input`)
keep working unchanged.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from ..schemas import ToolCall, ToolResult, ValidationResult
from ._base import (
    HandlerSpec,
    set_handlers_registry,
    truncate_result,
    validate_tool_input,
)

__all__ = [
    "HANDLERS",
    "HandlerSpec",
    "ToolCall",
    "ToolResult",
    "ValidationResult",
    "truncate_result",
    "validate_tool_input",
]


def _build_handlers() -> dict[str, HandlerSpec]:
    handlers: dict[str, HandlerSpec] = {}
    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f".{module_info.name}", package=__package__)
        module_handlers = getattr(module, "HANDLERS", None)
        if not module_handlers:
            continue
        handlers.update(module_handlers)
    # sorted() ensures deterministic order for any consumer that iterates
    # the registry (e.g., test snapshots, agent prompt builders).
    return dict(sorted(handlers.items(), key=lambda kv: kv[0]))


HANDLERS: dict[str, HandlerSpec] = _build_handlers()
set_handlers_registry(HANDLERS)


# Re-export so `from .handlers import handle_xxx` keeps working for any
# legacy caller that imported a specific handler function.
import importlib as _importlib  # noqa: E402  (after HANDLERS build)

for _name in list(HANDLERS.keys()):
    _short = _name.replace("tablex_", "")
    _mod = _importlib.import_module(f".{_short}", package=__package__)
    if hasattr(_mod, f"handle_{_short}"):
        globals()[f"handle_{_short}"] = getattr(_mod, f"handle_{_short}")
