import json
import sys
import urllib.request
import mimetypes

BASE = "http://127.0.0.1:8765"


def upload(path: str) -> str:
    boundary = "----demo"
    filename = path.split("/")[-1]
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        body = fh.read()
    payload = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode("utf-8") + body + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/files",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req).read())["file_id"]


def call(path: str, body: dict | None) -> dict:
    if body is not None:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(f"{BASE}{path}", method="GET")
    return json.loads(urllib.request.urlopen(req).read())


def run_demo(name: str, source: str, request_text: str) -> None:
    print(f"\n=== {name} ===")
    fid = upload(source)
    plan_resp = call("/api/plans", {"file_ids": [fid], "request": request_text})
    plan = plan_resp["plan"]
    kinds = [op["kind"] for op in plan["operations"]]
    token = f"confirm:{plan['id']}" if plan["requires_confirmation"] else None
    exec_resp = call(
        "/api/executions",
        {"file_ids": [fid], "plan": plan, "confirmation_token": token},
    )
    print(f"kinds: {kinds}")
    print(f"outputs: {plan['outputs']}")
    print(f"sheets: {exec_resp['sheets']}")
    print(f"conclusions: {len(exec_resp['conclusions'])}")


if __name__ == "__main__":
    run_demo(
        "personnel: dedup",
        "fixtures/personnel_messy.xlsx",
        "按证件号去重并生成问题清单",
    )
    run_demo(
        "project: filter status",
        "fixtures/project_progress_messy.xlsx",
        "筛选状态为进行中的项目",
    )
    print("\nall generalization paths completed")