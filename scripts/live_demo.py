import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"


def upload(path: str) -> str:
    import mimetypes
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


def call(path: str, body: dict) -> dict:
    if body:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(f"{BASE}{path}", method="GET")
    return json.loads(urllib.request.urlopen(req).read())


def main() -> None:
    request_text = "检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。"
    fid = upload("fixtures/expenses_and_budget.xlsx")
    print(f"uploaded: {fid}")
    plan_resp = call("/api/plans", {"file_ids": [fid], "request": request_text})
    plan = plan_resp["plan"]
    kinds = [op["kind"] for op in plan["operations"]]
    print(f"plan id: {plan['id']}")
    print(f"plan kinds: {kinds}")
    print(f"plan outputs: {plan['outputs']}")
    print(f"requires_confirmation: {plan['requires_confirmation']}")

    exec_resp = call(
        "/api/executions",
        {
            "file_ids": [fid],
            "plan": plan,
            "confirmation_token": f"confirm:{plan['id']}",
        },
    )
    output_id = exec_resp["output_id"]
    print(f"output_id: {output_id}")
    print(f"sheets: {exec_resp['sheets']}")
    print(f"conclusions: {[c['text'] for c in exec_resp['conclusions']]}")

    audit = call(f"/api/outputs/{output_id}/audit", {})
    step_ids = {e["step_id"] for e in audit["events"]}
    referenced = {c["source"]["step_id"] for c in exec_resp["conclusions"]}
    print(f"audit events: {len(audit['events'])}")
    print(f"step ids referenced by conclusions: {referenced}")
    print(f"step ids in audit: {step_ids}")
    print(f"all references valid: {referenced.issubset(step_ids)}")

    with open(f"runtime/outputs/{output_id}.xlsx", "rb") as fh:
        first_bytes = fh.read(4)
    print(f"downloaded file signature: {first_bytes}")
    print(f"is xlsx (PK): {first_bytes[:2] == b'PK'}")


if __name__ == "__main__":
    main()