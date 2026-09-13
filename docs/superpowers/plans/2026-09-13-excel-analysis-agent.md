# 表析 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable web application that accepts Excel/CSV files, inspects them, turns natural-language requests into validated spreadsheet operations, produces traceable analysis results, and downloads a new Excel workbook without changing the source file.

**Architecture:** Use a Python FastAPI backend with a deterministic spreadsheet domain layer. Pandas/openpyxl perform parsing, calculations, workbook creation, validation, and audit logging; the language model only produces a constrained operation plan and explanation. Use a React + TypeScript + Vite frontend for the three-pane workspace, with a local demo mode and an OpenAI-compatible model adapter behind the same backend interface.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pandas, openpyxl, xlrd, pytest, React, TypeScript, Vite, Vitest, Testing Library, and browser-native APIs. Use an OpenAI-compatible HTTP client only through the backend model adapter.

## Global Constraints

- First release supports `.xlsx`, `.xls`, and `.csv`; Word/PDF ingestion is a later extension and is excluded from the first implementation.
- Never overwrite an uploaded source file; every write operation creates a new output workbook.
- The executor accepts only typed, allow-listed operations and never executes model-generated arbitrary Python code.
- Delete, overwrite, deduplicate, or bulk formula-fill operations require an explicit confirmation token from the user.
- All important conclusions must carry source worksheet, column, filter, formula, or row references from the audit log.
- The backend must run without a model API key in `demo` mode so the sample workflow is reproducible.
- Use ASCII for new source comments and identifiers; user-facing Chinese copy belongs in frontend constants or response payloads.
- Every task ends with a focused test run and a separate Git commit.

---

## Project Structure

Create the following focused units:

```text
backend/
  app/
    main.py                 # FastAPI application and route registration
    config.py               # environment-backed settings
    schemas.py              # API and domain Pydantic models
    api/routes.py           # upload, inspect, plan, execute, download routes
    domain/parser.py        # workbook parsing and table-health inspection
    domain/operations.py    # allow-listed operation definitions and validation
    domain/executor.py      # deterministic dataframe/workbook execution
    domain/audit.py         # provenance events and conclusion references
    domain/service.py       # workflow orchestration for the API
    llm/base.py             # model adapter protocol
    llm/compatible.py       # OpenAI-compatible adapter
    llm/demo.py             # deterministic demo planner
  tests/
    test_parser.py
    test_executor.py
    test_service.py
    test_api.py
frontend/
  src/
    api.ts                  # typed backend client
    types.ts                # frontend response types
    App.tsx                 # workspace composition
    components/             # file list, plan, preview, cards, download
    __tests__/App.test.tsx
    test/setup.ts
    styles.css
  vitest.config.ts
fixtures/
  personnel_messy.xlsx
  project_progress_messy.xlsx
  expenses_and_budget.xlsx
README.md
```

The backend domain modules must be usable from tests without starting FastAPI. The API layer only validates requests, calls the service, and serializes typed results.

## Task 1: Initialize the backend and frontend skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/schemas.py`
- Create: `backend/app/main.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Produces `Settings`, `HealthResponse`, and `create_app()` for later tasks.
- `GET /api/health` returns `{ "status": "ok", "mode": "demo" | "llm" }`.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from backend.app.main import app


def test_health_reports_running_mode():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mode"] in {"demo", "llm"}
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: FAIL because the application modules and health route do not exist.

- [ ] **Step 3: Add the minimum project configuration and health app**

Implement `Settings` with `APP_MODE` defaulting to `demo`, define `HealthResponse`, create a FastAPI app, and register a `/api/health` route that returns the settings mode. Add the dependencies `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `pandas`, `openpyxl`, `xlrd`, `python-multipart`, and test dependencies `pytest`, `httpx` to `pyproject.toml`.

Create a Vite React TypeScript entry that renders `<App />`; `App` may initially render a single heading so the frontend build has a real entry point. Add frontend scripts `dev`, `build`, and `test`, runtime dependencies `react` and `react-dom`, and development dependencies `typescript`, `vite`, `@vitejs/plugin-react`, `vitest`, `jsdom`, `@testing-library/react`, and `@testing-library/jest-dom`. Configure `vitest.config.ts` with the `jsdom` environment and `src/test/setup.ts` as the setup file.

- [ ] **Step 4: Run backend and frontend checks**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: PASS.

Run: `npm install --prefix frontend; npm run build --prefix frontend`
Expected: Vite completes with an output bundle and no TypeScript errors.

- [ ] **Step 5: Commit the runnable skeleton**

```bash
git add pyproject.toml backend frontend
git commit -m "chore: scaffold spreadsheet agent"
```

## Task 2: Implement workbook parsing and table-health inspection

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/domain/parser.py`
- Create: `backend/tests/test_parser.py`

**Interfaces:**
- `inspect_workbook(path: Path) -> WorkbookInspection`
- `WorkbookInspection.sheets: list[SheetInspection]`
- `SheetInspection` contains `name`, `row_count`, `column_count`, `columns`, `preview`, and `issues`.
- `ColumnInspection` contains `name`, `inferred_type`, `null_count`, and `unique_count`.
- `DataIssue` contains `code`, `severity`, `message`, `sheet`, `column`, and optional `rows`.

- [ ] **Step 1: Write parser tests for mixed formats, duplicates, and empty values**

```python
from pathlib import Path
from openpyxl import Workbook
from backend.app.domain.parser import inspect_workbook


def test_inspection_detects_duplicate_rows_and_nulls(tmp_path: Path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "人员"
    sheet.append(["部门", "姓名", "金额"])
    sheet.append(["研发", "张三", "1,200"])
    sheet.append(["研发", "张三", "1,200"])
    sheet.append(["", "李四", None])
    source = tmp_path / "messy.xlsx"
    workbook.save(source)

    result = inspect_workbook(source)

    assert result.sheets[0].row_count == 3
    assert any(issue.code == "duplicate_rows" for issue in result.sheets[0].issues)
    assert any(issue.code == "null_values" for issue in result.sheets[0].issues)
```

- [ ] **Step 2: Run the parser test and verify it fails**

Run: `python -m pytest backend/tests/test_parser.py -q`
Expected: FAIL because `inspect_workbook` is not defined.

- [ ] **Step 3: Implement deterministic parsing**

Use `pandas.read_excel(sheet_name=None)` for `.xlsx`/`.xls` and `pandas.read_csv` for `.csv`. Drop only fully empty rows and columns. Infer types using pandas dtypes plus a numeric/date coercion probe. Detect duplicate rows, null cells, mixed numeric text, and columns with more than one normalized spelling for date-like values. Return at most 20 preview rows per sheet and row numbers as one-based spreadsheet row references.

- [ ] **Step 4: Add parser edge-case tests and run them**

Cover CSV input, a workbook with an empty sheet, a missing file, and an unsupported extension. Assert errors are typed as `FileNotFoundError` or `ValueError` with the extension in the message for unsupported files.

Run: `python -m pytest backend/tests/test_parser.py -q`
Expected: PASS.

- [ ] **Step 5: Commit the parser**

```bash
git add backend/app/schemas.py backend/app/domain/parser.py backend/tests/test_parser.py
git commit -m "feat: inspect spreadsheet health"
```

## Task 3: Build the allow-listed operation model and deterministic executor

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/domain/operations.py`
- Create: `backend/app/domain/executor.py`
- Create: `backend/app/domain/audit.py`
- Create: `backend/tests/test_executor.py`

**Interfaces:**
- `OperationPlan(id, source_sheets, operations, outputs, requires_confirmation, explanation)`.
- Supported operation kinds: `normalize`, `deduplicate`, `filter`, `group_summary`, `compare`, `fill_formula`, and `create_issue_sheet`.
- `execute_plan(source_paths: list[Path], plan: OperationPlan, confirmation_token: str | None) -> ExecutionResult`.
- `ExecutionResult.output_path`, `sheets`, `metrics`, `conclusions`, and `audit_events`.
- `AuditEvent.step_id`, `operation`, `sheet`, `columns`, `affected_rows`, `details`.

- [ ] **Step 1: Write failing executor tests for grouping, deduplication, and confirmation**

```python
def test_execute_plan_creates_new_workbook_and_audit_events(messy_workbook):
    plan = OperationPlan(
        id="plan-1",
        source_sheets=["明细"],
        operations=[
            NormalizeOperation(sheet="明细", columns=["金额"], target_type="number"),
            DeduplicateOperation(sheet="明细", key_columns=["订单号"]),
            GroupSummaryOperation(sheet="明细", group_by=["部门"], metrics={"金额": ["sum"]}),
        ],
        outputs=["清洗后数据", "部门汇总"],
        requires_confirmation=True,
        explanation="统一金额并按订单号去重后汇总部门金额",
    )

    with pytest.raises(ConfirmationRequired):
        execute_plan([messy_workbook], plan, confirmation_token=None)

    result = execute_plan([messy_workbook], plan, confirmation_token="confirm:plan-1")
    assert result.output_path.exists()
    assert {"清洗后数据", "部门汇总"} <= set(result.sheets)
    assert any(event.operation == "deduplicate" for event in result.audit_events)
```

- [ ] **Step 2: Run the executor test and verify it fails**

Run: `python -m pytest backend/tests/test_executor.py -q`
Expected: FAIL because operation models and executor do not exist.

- [ ] **Step 3: Implement typed operations and confirmation policy**

Define each operation as a Pydantic discriminated union. Mark `deduplicate`, `fill_formula`, and any operation with `overwrite=True` as high impact. Require the exact token `confirm:<plan.id>` for those plans. Reject unknown operation kinds, missing columns, invalid aggregation names, and formula fill ranges that are outside the source data range.

- [ ] **Step 4: Implement execution and audit logging**

Load source sheets into dataframes, apply operations in plan order, and write a new workbook under an application-managed output directory. Preserve an untouched copy of the source sheets, add requested result sheets, and write a hidden `_audit` sheet containing JSON lines for reproducibility. Each operation must record input row count, output row count, affected rows, and parameters. Generate numeric metrics from the resulting dataframes, never from model text.

- [ ] **Step 5: Add tests for compare, formula fill, and output validation**

Assert compare emits `added`, `removed`, and `changed` rows by key; formula fill writes formulas into blank cells only; reopening the output workbook succeeds; and the source file hash is unchanged.

Run: `python -m pytest backend/tests/test_executor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit the deterministic engine**

```bash
git add backend/app/schemas.py backend/app/domain/operations.py backend/app/domain/executor.py backend/app/domain/audit.py backend/tests/test_executor.py
git commit -m "feat: execute audited spreadsheet plans"
```

## Task 4: Add planning adapters and workflow service

**Files:**
- Create: `backend/app/llm/base.py`
- Create: `backend/app/llm/demo.py`
- Create: `backend/app/llm/compatible.py`
- Create: `backend/app/domain/service.py`
- Create: `backend/tests/test_service.py`

**Interfaces:**
- `Planner.plan(request: str, inspection: WorkbookInspection) -> OperationPlan`.
- `DemoPlanner` recognizes the demo commands for inspect/clean/summarize, compare, and formula fill.
- `CompatiblePlanner` sends a JSON-schema-constrained request and parses only `OperationPlan`.
- `analyze_files(paths: list[Path]) -> WorkbookInspection`.
- `create_plan(paths: list[Path], request: str) -> OperationPlan`.
- `run_plan(paths: list[Path], plan: OperationPlan, confirmation_token: str | None) -> ExecutionResult`.

- [ ] **Step 1: Write failing service tests**

```python
def test_demo_planner_turns_natural_language_into_typed_plan(sample_file):
    plan = create_plan([sample_file], "检查数据问题，统一金额格式并按部门汇总")
    assert any(operation.kind == "normalize" for operation in plan.operations)
    assert any(operation.kind == "group_summary" for operation in plan.operations)
    assert plan.requires_confirmation is True
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest backend/tests/test_service.py -q`
Expected: FAIL because no planner or service exists.

- [ ] **Step 3: Implement the demo planner**

Select columns from inspection metadata using exact normalized matches first, then aliases for `金额`, `日期`, `部门`, `订单号`, `编号`, and `状态`. Return a clarification error when required fields cannot be resolved. The demo planner must support the primary competition phrase and produce a plan that writes `清洗后数据`, `汇总结果`, and `问题清单`.

- [ ] **Step 4: Implement the compatible model adapter**

Use `MODEL_BASE_URL`, `MODEL_API_KEY`, and `MODEL_NAME` from settings. Send the inspection summary and user request with an explicit JSON schema for `OperationPlan`; reject non-JSON or schema-invalid responses and return an actionable error. Do not expose the API key to the frontend.

- [ ] **Step 5: Implement service orchestration and tests**

The service must inspect before planning, preserve the original paths, pass only validated plans to the executor, and return typed errors for ambiguity and unsupported files. Test the full demo workflow from file to output workbook and assert the conclusion references point to audit events.

Run: `python -m pytest backend/tests/test_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit planning and service layers**

```bash
git add backend/app/llm backend/app/domain/service.py backend/tests/test_service.py
git commit -m "feat: add spreadsheet planning workflow"
```

## Task 5: Expose the workflow through the FastAPI API

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api.py`

**Interfaces:**
- `POST /api/files` multipart upload returns `FileUploadResponse` with `file_id`, `filename`, and `inspection`.
- `POST /api/plans` JSON `{file_ids, request}` returns `PlanResponse`.
- `POST /api/executions` JSON `{file_ids, plan, confirmation_token}` returns `ExecutionResponse`.
- `GET /api/outputs/{output_id}` streams the generated `.xlsx` file.
- `GET /api/outputs/{output_id}/audit` returns audit events and conclusion references.

- [ ] **Step 1: Write API contract tests**

```python
def test_upload_plan_execute_and_download(client, sample_file):
    upload = client.post("/api/files", files={"file": ("sample.xlsx", sample_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert upload.status_code == 201
    file_id = upload.json()["file_id"]
    assert upload.json()["inspection"]["sheets"]

    planned = client.post("/api/plans", json={"file_ids": [file_id], "request": "按部门汇总金额"})
    assert planned.status_code == 200
    plan = planned.json()["plan"]

    executed = client.post("/api/executions", json={"file_ids": [file_id], "plan": plan, "confirmation_token": "confirm:" + plan["id"]})
    assert executed.status_code == 201
    downloaded = client.get("/api/outputs/" + executed.json()["output_id"])
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/vnd.openxmlformats")
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run: `python -m pytest backend/tests/test_api.py -q`
Expected: FAIL because the routes are not registered.

- [ ] **Step 3: Implement bounded file storage and routes**

Store uploads and outputs under `runtime/uploads` and `runtime/outputs`, generate UUID identifiers, limit uploads to 25 MB, and allow only the three configured extensions. Use `FileResponse` for downloads and `HTTPException` responses with stable error codes: `unsupported_file`, `ambiguous_request`, `confirmation_required`, and `execution_failed`.

- [ ] **Step 4: Complete API integration tests**

Test malformed plan JSON, missing file IDs, unsupported extension, missing confirmation, and a download of a real output. Assert source files remain present after execution.

Run: `python -m pytest backend/tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit the API**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat: expose spreadsheet workflow api"
```

## Task 6: Build the three-pane frontend workspace

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/__tests__/App.test.tsx`
- Create: `frontend/src/components/FilePanel.tsx`
- Create: `frontend/src/components/TaskPanel.tsx`
- Create: `frontend/src/components/InspectionPanel.tsx`
- Create: `frontend/src/components/PlanPanel.tsx`
- Create: `frontend/src/components/ResultPanel.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `uploadFile(file: File): Promise<FileUploadResponse>`.
- `createPlan(fileIds: string[], request: string): Promise<PlanResponse>`.
- `executePlan(input: ExecuteRequest): Promise<ExecutionResponse>`.
- `downloadUrl(outputId: string): string`.

- [ ] **Step 1: Add frontend client types and write component tests**

Use Vitest + Testing Library. Test that uploading a file renders its workbook and sheet, entering a request renders a plan, clicking the confirmation action sends the exact plan ID token, and the result panel renders a download link and at least one conclusion card.

- [ ] **Step 2: Run frontend tests and verify the new tests fail**

Run: `npm install --prefix frontend; npm run test --prefix frontend -- --run`
Expected: FAIL because the components and client functions are not implemented.

- [ ] **Step 3: Implement the file panel and inspection panel**

Use a file input accepting `.xlsx,.xls,.csv`, show upload progress and errors, list files and sheets, and display row/column counts plus issue severity. Keep the source file list visible after a result is created.

- [ ] **Step 4: Implement the task and plan panels**

Provide a natural-language textarea, submit button, loading state, and plan rendering with source sheets, selected columns, operations, outputs, and confirmation warning. Disable execution until a plan exists; require a second click for plans marked `requires_confirmation`.

- [ ] **Step 5: Implement the result panel and responsive styling**

Render conclusion cards, before/after metrics, expandable provenance details, an execution error state, and a real download link. Use a dense three-column desktop layout that collapses to stacked sections below 900px. Do not use decorative marketing hero content; the first screen is the working workspace.

- [ ] **Step 6: Run tests and production build**

Run: `npm run test --prefix frontend -- --run`
Expected: PASS.

Run: `npm run build --prefix frontend`
Expected: PASS with no TypeScript errors.

- [ ] **Step 7: Commit the workspace UI**

```bash
git add frontend
git commit -m "feat: add spreadsheet analysis workspace"
```

## Task 7: Create reproducible demo workbooks and end-to-end verification

**Files:**
- Create: `scripts/create_fixtures.py`
- Create: `fixtures/README.md`
- Create: `backend/tests/test_end_to_end.py`
- Create: `README.md`

**Interfaces:**
- `python scripts/create_fixtures.py` creates the three named workbooks deterministically.
- README documents demo startup, supported files, the primary prompt, confirmation behavior, and download location.

- [ ] **Step 1: Write the end-to-end test against generated fixtures**

```python
def test_primary_demo_prompt_produces_audited_download(client, fixture_dir):
    response = upload_and_execute(client, fixture_dir / "expenses_and_budget.xlsx", "检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。")
    assert response.status_code == 201
    result = response.json()
    assert result["conclusions"]
    assert "问题清单" in result["sheets"]
    assert client.get(f"/api/outputs/{result['output_id']}").status_code == 200
```

- [ ] **Step 2: Run it and verify it fails before fixtures and full wiring exist**

Run: `python -m pytest backend/tests/test_end_to_end.py -q`
Expected: FAIL because the fixture generator and helper workflow are not present.

- [ ] **Step 3: Generate the three intentionally messy datasets**

Create deterministic workbooks containing mixed date formats, numeric text with commas, duplicate rows, blank fields, inconsistent category spellings, invalid status values, and a second comparison sheet where rows are added, removed, and changed. Do not use real personal data; use fictional Chinese names and synthetic identifiers.

- [ ] **Step 4: Add startup and demo documentation**

Document:

```text
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python scripts/create_fixtures.py
uvicorn backend.app.main:app --reload --port 8000
npm install --prefix frontend
npm run dev --prefix frontend
```

Explain that the browser uses the API at `http://localhost:8000`, demo mode needs no model key, and LLM mode requires the three model environment variables.

- [ ] **Step 5: Run the full verification suite**

Run: `python -m pytest -q`
Expected: all backend tests pass.

Run: `npm run test --prefix frontend -- --run; npm run build --prefix frontend`
Expected: all frontend tests pass and the production build succeeds.

Run: `python scripts/create_fixtures.py`
Expected: all three fixture files are created under `fixtures/`.

- [ ] **Step 6: Commit demo assets and documentation**

```bash
git add scripts fixtures backend/tests/test_end_to_end.py README.md
git commit -m "test: add reproducible spreadsheet demos"
```

## Task 8: Final quality gate and live demo check

**Files:**
- Modify: any implementation file required by failed verification only.
- Create: `docs/demo-script.md`

- [ ] **Step 1: Start backend and frontend locally**

Run backend with `uvicorn backend.app.main:app --port 8000` and frontend with `npm run dev --prefix frontend`. Use the Vite URL shown in the terminal.

- [ ] **Step 2: Execute the five-minute competition path**

Upload `fixtures/expenses_and_budget.xlsx`, wait for the inspection, enter the primary prompt, inspect the plan, confirm the high-impact operations, download the new workbook, and open it in Excel. Verify that the source workbook is unchanged and the output contains cleaned data, summary, issue list, and `_audit` sheet.

- [ ] **Step 3: Test the two generalization paths**

Upload `fixtures/personnel_messy.xlsx` and request duplicate removal plus missing-value inspection. Upload `fixtures/project_progress_messy.xlsx` and request overdue filtering plus status summary. Verify the same workflow works without changing the UI or adding a scenario-specific route.

- [ ] **Step 4: Capture final evidence**

Record screenshots of the inspection, plan confirmation, result cards, provenance expansion, and downloaded workbook. Record a short demo video only after the live path succeeds twice consecutively.

- [ ] **Step 5: Commit only fixes discovered in the live check**

```bash
git add backend frontend docs/demo-script.md
git commit -m "chore: validate competition demo"
```

## Spec Coverage Review

- Upload and inspect Excel/CSV: Tasks 1, 2, and 5.
- Natural-language planning with constrained execution: Task 4.
- Cleaning, summary, comparison, and formula operations: Task 3.
- New output workbook, source preservation, confirmation, and audit: Tasks 3 and 5.
- Three-pane workspace and result cards: Task 6.
- Ambiguity and unsupported-file errors: Tasks 2, 4, and 5.
- Reproducible non-industry-specific demo data: Task 7.
- Live competition workflow and acceptance evidence: Task 8.

## Plan Self-Review

- No placeholder markers or unspecified implementation task remains.
- Operation names and response types are introduced before they are consumed.
- The deterministic engine is independent of FastAPI and the model adapter.
- The first release remains Excel/CSV-focused; Word/PDF is explicitly deferred as required by the design specification.
- The plan yields independently testable commits and finishes with a live end-to-end check.
