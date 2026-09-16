"""End-to-end example: walk through every supported workflow.

Usage:
    python scripts/example_workflow.py

The script uploads each fixture, drives the full upload → plan → confirm →
execute → audit chain, prints a short report, and downloads the output
file into ./runtime/example_outputs/ for inspection.
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8000"
OUTPUT_DIR = Path("runtime/example_outputs")


def upload(path: Path) -> dict[str, Any]:
    boundary = "----example"
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = path.read_bytes()
    payload = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode("utf-8") + body + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/files",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def post(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if body is None:
        req = urllib.request.Request(f"{BASE}{path}", method="GET")
    else:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"_status": exc.code, "_body": json.loads(exc.read())}


def get_bytes(path: str) -> bytes:
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def run_case(
    name: str,
    fixture: str,
    request_text: str,
    confirm: bool = True,
) -> dict[str, Any]:
    print(f"\n=== {name} ===")
    print(f"fixture:    {fixture}")
    print(f"request:    {request_text}")
    uploaded = upload(Path(fixture))
    file_id = uploaded["file_id"]
    sheets = uploaded["inspection"]["sheets"]
    for sheet in sheets:
        issues = sheet["issues"]
        print(f"  [{sheet['name']}] {sheet['row_count']} 行 × {sheet['column_count']} 列 · 问题 {len(issues)}")
        for issue in issues[:3]:
            print(f"    - [{issue['severity']}] {issue['code']}: {issue['message']}")

    plan_resp = post("/api/plans", {"file_ids": [file_id], "request": request_text})
    if "_status" in plan_resp:
        print(f"plan error: {plan_resp}")
        return plan_resp
    plan = plan_resp["plan"]
    kinds = [op["kind"] for op in plan["operations"]]
    print(f"plan id:    {plan['id']}")
    print(f"kinds:      {kinds}")
    print(f"outputs:    {plan['outputs']}")
    print(f"confirm:    {plan['requires_confirmation']}")
    print(f"explain:    {plan['explanation']}")

    token = f"confirm:{plan['id']}" if (plan["requires_confirmation"] and confirm) else None
    if plan["requires_confirmation"] and not confirm:
        print("(演示跳过确认)")
    exec_resp = post(
        "/api/executions",
        {"file_ids": [file_id], "plan": plan, "confirmation_token": token},
    )
    if "_status" in exec_resp:
        print(f"exec error: {exec_resp}")
        return exec_resp
    output_id = exec_resp["output_id"]
    print(f"output id:  {output_id}")
    print(f"sheets:     {exec_resp['sheets']}")
    print(f"metrics:    {exec_resp['metrics']}")
    for c in exec_resp["conclusions"]:
        print(f"  · [{c['severity']}] {c['text']} (step {c['source']['step_id']})")

    audit = post(f"/api/outputs/{output_id}/audit")
    step_ids = {e["step_id"] for e in audit["events"]}
    referenced = {c["source"]["step_id"] for c in exec_resp["conclusions"]}
    print(f"audit events: {len(audit['events'])}")
    print(f"  step_ids: {sorted(step_ids)}")
    print(f"  conclusions reference real steps: {referenced.issubset(step_ids)}")

    body = get_bytes(f"/api/outputs/{output_id}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{name}.xlsx"
    out_path.write_bytes(body)
    print(f"downloaded: {out_path} ({len(body)} bytes)")
    return {"output_id": output_id, "sheets": exec_resp["sheets"]}


def main() -> None:
    print(f"Backend: {BASE}")
    health = post("/api/health")
    print(f"Health:  {health}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in OUTPUT_DIR.glob("*.xlsx"):
        f.unlink()

    run_case(
        "01_main_demo",
        "fixtures/expenses_and_budget.xlsx",
        "检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。",
        confirm=True,
    )

    run_case(
        "02_personnel_dedup",
        "fixtures/personnel_messy.xlsx",
        "按证件号去重并生成问题清单",
        confirm=True,
    )

    run_case(
        "03_project_filter",
        "fixtures/project_progress_messy.xlsx",
        "筛选状态为进行中的项目",
        confirm=True,
    )

    print("\n=== Done ===")
    print(f"输出文件已写入 {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()