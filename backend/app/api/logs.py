"""GET /api/logs/recent — tail the in-memory ring buffer."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..logging_setup import get_ring


def create_logs_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/logs/recent")
    def recent_logs(lines: int = Query(200, ge=1, le=1000)) -> dict[str, object]:
        ring = get_ring()
        snapshot = ring.snapshot()
        return {
            "lines": snapshot[-lines:],
            "total_lines": len(snapshot),
        }

    return router
