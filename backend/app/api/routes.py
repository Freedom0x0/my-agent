"""FastAPI routes for upload, plan, execute, download, and audit."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..config import get_settings
from ..db import (
    FileRecord,
    OutputRecord,
    get_file,
    get_output,
    get_session_detail,
    get_workflow,
    init_db,
    insert_file,
    insert_output,
    list_session_files,
    list_sessions,
)
from ..logging_setup import get_ring
from ..mcp import engine as engine_module
from ..mcp.session import get_session_store
from ..mcp.workflow import public_graph
from ..domain._archive.operations import (
    ConfirmationRequired,
    InvalidPlanError,
    expected_confirmation_token,
)
from ..domain.parser import (
    INTERNAL_COL,
    UnsupportedFileError,
    inspect_workbook,
    load_tables,
)
from ..domain.service import (
    AmbiguousRequestServiceError,
    ServiceError,
    UnsupportedFileServiceError,
    create_plan as service_create_plan,
    run_plan_with_tables,
)
from ..schemas import (
    AuditResponse,
    ErrorResponse,
    ExecuteRequest,
    ExecutionResponse,
    FileUploadResponse,
    PlanResponse,
)


def _settings_data_dir() -> Path:
    settings = get_settings()
    base = Path(settings.APP_DATA_DIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _db_path() -> Path:
    return _settings_data_dir() / "metadata.db"


def _uploads_dir() -> Path:
    base = _settings_data_dir()
    uploads = base / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


def _outputs_dir() -> Path:
    base = _settings_data_dir()
    outputs = base / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    return outputs


def _file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _verify_within(base: Path, target: Path) -> Path:
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if not str(target_resolved).startswith(str(base_resolved)):
        raise HTTPException(status_code=400, detail="invalid_request")
    return target_resolved


def _build_error(code: str, message: str, status: int, details: dict[str, Any] | None = None) -> HTTPException:
    payload = ErrorResponse(error_code=code, message=message, details=details or {}).model_dump()
    return HTTPException(status_code=status, detail=payload)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    init_db(_db_path())
    settings = get_settings()

    @router.post(
        "/files",
        response_model=FileUploadResponse,
        status_code=201,
        responses={
            400: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
        },
    )
    async def upload_file(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None),
    ) -> FileUploadResponse:
        if not file.filename:
            raise _build_error("invalid_request", "缺少文件名", 400)
        ext = _file_extension(file.filename)
        if ext not in {".xlsx", ".xls", ".csv"}:
            raise _build_error(
                "unsupported_file",
                f"不支持的扩展名 {ext}",
                400,
            )

        contents = await file.read()
        if len(contents) > settings.MAX_UPLOAD_BYTES:
            raise _build_error(
                "file_too_large",
                f"文件超过 {settings.MAX_UPLOAD_BYTES} 字节",
                413,
            )
        if len(contents) == 0:
            raise _build_error("invalid_request", "空文件", 400)

        file_id = uuid.uuid4().hex
        stored_name = f"{file_id}{ext}"
        stored_path = _uploads_dir() / stored_name
        stored_path.write_bytes(contents)
        sha = hashlib.sha256(contents).hexdigest()

        try:
            inspection = inspect_workbook(stored_path)
        except UnsupportedFileError as exc:
            stored_path.unlink(missing_ok=True)
            raise _build_error("unsupported_file", str(exc), 400)
        except FileNotFoundError as exc:
            stored_path.unlink(missing_ok=True)
            raise _build_error("file_not_found", str(exc), 404)

        record = FileRecord(
            file_id=file_id,
            original_name=file.filename,
            stored_path=str(stored_path),
            file_type=ext.lstrip("."),
            size_bytes=len(contents),
            sha256=sha,
            inspection=inspection.model_dump(),
            created_at=_dt.datetime.utcnow().isoformat(),
            session_id=(session_id or "").strip() or None,
        )
        insert_file(_db_path(), record)
        return FileUploadResponse(
            file_id=file_id,
            filename=file.filename,
            size_bytes=len(contents),
            inspection=inspection,
        )

    @router.get(
        "/files/{file_id}/content",
        responses={404: {"model": ErrorResponse}},
    )
    async def download_file_content(file_id: str):
        """Hand back the original bytes so the client can rebuild a preview.

        Previews are parsed client-side from the real workbook; without this the
        client has no way back to the bytes after a reload.
        """
        rec = get_file(_db_path(), file_id)
        if rec is None:
            raise _build_error("file_not_found", f"未找到文件 {file_id}", 404)
        path = _verify_within(_uploads_dir(), Path(rec.stored_path))
        if not path.exists():
            raise _build_error("file_not_found", "文件已丢失", 404)
        return FileResponse(path=str(path), filename=rec.original_name)

    @router.post(
        "/plans",
        response_model=PlanResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def create_plan_route(payload: dict[str, Any]) -> PlanResponse:
        file_ids = payload.get("file_ids") or []
        request_text = (payload.get("request") or "").strip()
        if not file_ids or not isinstance(file_ids, list):
            raise _build_error("invalid_request", "file_ids 不能为空", 400)
        if not request_text:
            raise _build_error("invalid_request", "request 不能为空", 400)
        if len(request_text) > 2000:
            raise _build_error("invalid_request", "request 不能超过 2000 字", 400)

        file_id_to_paths: dict[str, Path] = {}
        for fid in file_ids:
            rec = get_file(_db_path(), fid)
            if rec is None:
                raise _build_error("file_not_found", f"未找到文件 {fid}", 404)
            file_id_to_paths[fid] = Path(rec.stored_path)

        try:
            plan = service_create_plan(file_id_to_paths, request_text)
        except UnsupportedFileServiceError as exc:
            raise _build_error("unsupported_file", str(exc), 400)
        except AmbiguousRequestServiceError as exc:
            raise _build_error("ambiguous_request", str(exc), 400)

        return PlanResponse(plan=plan)

    @router.post(
        "/executions",
        response_model=ExecutionResponse,
        status_code=201,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    async def execute_route(payload: ExecuteRequest) -> ExecutionResponse:
        file_id_to_paths: dict[str, Path] = {}
        for fid in payload.file_ids:
            rec = get_file(_db_path(), fid)
            if rec is None:
                raise _build_error("file_not_found", f"未找到文件 {fid}", 404)
            file_id_to_paths[fid] = Path(rec.stored_path)

        tables: dict[str, pd.DataFrame] = {}
        try:
            for fid, path in file_id_to_paths.items():
                for sheet_name, df in load_tables(path).items():
                    tables[f"{fid}::{sheet_name}"] = df
        except UnsupportedFileError as exc:
            raise _build_error("unsupported_file", str(exc), 400)

        output_id = uuid.uuid4().hex
        output_path = _outputs_dir() / f"{output_id}.xlsx"
        try:
            result = run_plan_with_tables(
                tables, payload.plan, payload.confirmation_token, output_path,
            )
        except ConfirmationRequired as exc:
            raise _build_error(
                "confirmation_required",
                "该操作会修改或删除数据，请确认影响范围后继续。",
                409,
                {"affected_rows": exc.affected_rows},
            )
        except InvalidPlanError as exc:
            raise _build_error("invalid_plan", str(exc), 400)
        except Exception as exc:
            raise _build_error("execution_failed", f"执行失败: {exc}", 500)

        result_dict = result.model_dump()
        plan_dict = payload.plan.model_dump()
        record = OutputRecord(
            output_id=output_id,
            stored_path=str(output_path),
            source_file_ids=payload.file_ids,
            plan=plan_dict,
            result=result_dict,
            status="completed",
            created_at=_dt.datetime.utcnow().isoformat(),
        )
        insert_output(_db_path(), record)

        return ExecutionResponse(
            output_id=output_id,
            sheets=result.sheets,
            metrics=result.metrics,
            conclusions=result.conclusions,
            audit_events=result.audit_events,
        )

    @router.get(
        "/outputs/{output_id}",
        responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    )
    async def download_output(output_id: str):
        rec = get_output(_db_path(), output_id)
        if rec is None:
            raise _build_error("output_not_found", f"未找到输出 {output_id}", 404)
        path = _verify_within(_outputs_dir(), Path(rec.stored_path))
        if not path.exists():
            raise _build_error("output_not_found", "输出文件已丢失", 404)
        return FileResponse(
            path=str(path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=path.name,
        )

    @router.get(
        "/outputs/{output_id}/audit",
        response_model=AuditResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_audit(output_id: str) -> AuditResponse:
        rec = get_output(_db_path(), output_id)
        if rec is None:
            raise _build_error("output_not_found", f"未找到输出 {output_id}", 404)
        events = rec.result.get("audit_events", [])
        conclusions = rec.result.get("conclusions", [])
        return AuditResponse(output_id=output_id, events=events, conclusions=conclusions)

    @router.get("/logs/recent")
    async def logs_recent(
        lines: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Tail of the in-process log ring — what the log panel polls.

        Read from the ring buffer rather than the file so it works without a
        writable log directory, and so it can't be swamped by rotation.
        """
        snapshot = get_ring().snapshot()
        return {"total_lines": len(snapshot), "lines": snapshot[-lines:]}

    @router.get("/sessions")
    async def list_sessions_route() -> dict[str, Any]:
        return {"sessions": list_sessions(_db_path())}

    @router.get(
        "/sessions/{session_id}",
        responses={404: {"model": ErrorResponse}},
    )
    async def get_session_route(
        session_id: str,
        limit: int | None = Query(default=None, ge=1, le=500),
        before_index: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        detail = get_session_detail(
            _db_path(),
            session_id,
            limit=limit,
            before_index=before_index,
        )
        if detail is None:
            raise _build_error("session_not_found", f"未找到会话 {session_id}", 404)
        return detail

    @router.get(
        "/sessions/{session_id}/workflow",
        responses={404: {"model": ErrorResponse}},
    )
    async def get_session_workflow(session_id: str) -> dict[str, Any]:
        """The session's workflow graph + stage (nodes carry their derived seq)."""
        saved = get_workflow(_db_path(), session_id)
        if saved is None:
            raise _build_error("workflow_not_found", f"未找到工作流 {session_id}", 404)
        return {
            "session_id": session_id,
            "stage": saved["stage"],
            **public_graph(saved["graph"]),
        }

    @router.post(
        "/sessions/{session_id}/workflow/execute",
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def execute_session_workflow(session_id: str) -> StreamingResponse:
        """Approve and run the graph; stream node-level events as SSE.

        This is the 「执行」 button: it advances the stage to `executing` and drives
        the engine. Node outputs land on disk and in the graph row as they finish.
        """
        store = get_session_store()
        session = store.get_or_create(session_id)
        if session.graph is None:
            raise _build_error("workflow_not_found", f"未找到工作流 {session_id}", 404)
        if session.stage == "executing":
            raise _build_error("execution_in_progress", "工作流正在执行中", 409)
        # After a restart (or a fresh process) the session's files live only in
        # SQLite, but the handlers read them from `session.files` — reload them or
        # every source node fails with "文件不存在".
        for rec in list_session_files(_db_path(), session_id):
            session.files.setdefault(
                rec.file_id,
                {
                    "path": rec.stored_path,
                    "sha256": rec.sha256,
                    "original_name": rec.original_name,
                    "inspection": rec.inspection,
                },
            )
        return StreamingResponse(
            _sse_stream(engine_module.execute_graph_stream(session, store=store)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post(
        "/sessions/{session_id}/workflow/pause",
        responses={404: {"model": ErrorResponse}},
    )
    async def pause_session_workflow(session_id: str) -> dict[str, Any]:
        """Request a pause: the run stops starting new nodes and lets the current
        one finish (pandas work can't be interrupted mid-node)."""
        store = get_session_store()
        session = store.get(session_id)
        if session is None:
            raise _build_error("session_not_found", f"未找到会话 {session_id}", 404)
        session.pause_requested = True
        return {"session_id": session_id, "stage": session.stage, "pause_requested": True}

    return router


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _sse_stream(source: Any):
    async for event in source:
        yield _sse(event)