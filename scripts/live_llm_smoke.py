import json
import urllib.request
import urllib.error
import mimetypes

BASE = "http://127.0.0.1:8000"


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


def call(path: str, body: dict | None = None) -> tuple[int, dict]:
    if body is not None:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(f"{BASE}{path}", method="GET")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": str(e)}


def main() -> None:
    fid = upload("fixtures/expenses_and_budget.xlsx")
    print(f"uploaded: {fid}")
    plan_status, plan_resp = call("/api/plans", {
        "file_ids": [fid],
        "request": "按订单号去重",
    })
    print(f"plan status: {plan_status}")
    if plan_status != 200:
        print(f"plan error: {plan_resp}")
        return
    plan = plan_resp["plan"]
    print(f"plan id: {plan['id']}")
    print(f"kinds: {[op['kind'] for op in plan['operations']]}")
    print(f"outputs: {plan['outputs']}")
    print(f"requires_confirmation: {plan['requires_confirmation']}")
    print(f"explanation: {plan['explanation']}")
    print(f"source_sheets: {plan['source_sheets']}")

    exec_status, exec_resp = call("/api/executions", {
        "file_ids": [fid],
        "plan": plan,
        "confirmation_token": f"confirm:{plan['id']}" if plan["requires_confirmation"] else None,
    })
    print(f"\nexec status: {exec_status}")
    if exec_status != 201:
        print(f"exec error: {exec_resp}")
        return
    print(f"sheets: {exec_resp['sheets']}")
    print(f"conclusions: {len(exec_resp['conclusions'])}")
    for c in exec_resp["conclusions"]:
        print(f"  - [{c['severity']}] {c['text']} (step={c['source']['step_id']})")

    audit_status, audit = call(f"/api/outputs/{exec_resp['output_id']}/audit")
    print(f"\naudit status: {audit_status}")
    print(f"audit events: {len(audit['events'])}")
    step_ids = {e['step_id'] for e in audit['events']}
    referenced = {c['source']['step_id'] for c in exec_resp['conclusions']}
    print(f"all conclusions reference real step_ids: {referenced.issubset(step_ids)}")


if __name__ == "__main__":
    main()