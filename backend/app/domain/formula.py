"""Formula extraction + dependency graph from openpyxl workbooks.

ponytail: regex-based cell-reference extraction (A1, $A$1) only. Upgrade
path: ship a real formula parser (formulas / pycel) when nested functions
or cross-sheet refs (Sheet1!A1) become a hard requirement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from openpyxl import Workbook

# Matches A1-style refs, optionally with $-anchors.
_CELL_REF = re.compile(r"\$?([A-Z]+)\$?(\d+)")


@dataclass
class FormulaInfo:
    cell: str
    formula: str


def extract_formulas(workbook: Workbook, sheet_name: str) -> list[FormulaInfo]:
    """Read all formula cells from a sheet. Workbook must be opened data_only=False."""
    ws = workbook[sheet_name]
    out: list[FormulaInfo] = []
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if isinstance(v, str) and v.startswith("="):
                out.append(FormulaInfo(cell=cell.coordinate, formula=v))
    return out


def build_dependency_graph(formulas: Iterable[FormulaInfo]) -> dict[str, list[str]]:
    """Parse each formula and return {cell: [ref_cells...]}."""
    graph: dict[str, list[str]] = {}
    for f in formulas:
        body = f.formula[1:] if f.formula.startswith("=") else f.formula
        deps: list[str] = []
        seen: set[str] = set()
        for match in _CELL_REF.finditer(body):
            ref = f"{match.group(1)}{match.group(2)}"
            if ref not in seen:
                seen.add(ref)
                deps.append(ref)
        graph[f.cell] = deps
    return graph


def find_circular(graph: dict[str, list[str]]) -> list[list[str]]:
    """Find all circular dependency cycles via DFS; returns each cycle as a list of cells.

    A cell with no outgoing deps is a leaf; a cycle means A -> B -> ... -> A.
    """
    cycles: list[list[str]] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    parent: dict[str, str | None] = {n: None for n in graph}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for nxt in graph.get(node, []):
            if nxt not in color:
                # External ref (e.g. cell outside the known graph) — skip silently.
                continue
            if color[nxt] == GRAY:
                # Found a back-edge -> cycle from nxt .. node.
                idx = path.index(nxt)
                cycle = path[idx:] + [nxt]
                cycles.append(cycle)
            elif color[nxt] == WHITE:
                parent[nxt] = node
                dfs(nxt, path)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node, [])

    # De-duplicate cycles (same cycle discovered from different entry points).
    unique: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for cyc in cycles:
        # Rotate so the smallest element comes first for canonical form.
        body = cyc[:-1]
        if not body:
            continue
        k = min(range(len(body)), key=lambda i: body[i])
        rotated = tuple(body[k:] + body[:k])
        if rotated not in seen_keys:
            seen_keys.add(rotated)
            unique.append(list(rotated) + [rotated[0]])
    return unique
