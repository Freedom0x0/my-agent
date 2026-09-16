import json, urllib.request, urllib.error, mimetypes, sys
from pathlib import Path

BASE = "http://127.0.0.1:8001"

def upload(path):
    boundary = "----t"
    with open(path, "rb") as f:
        body = f.read()
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + body + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f'{BASE}/api/files', data=payload, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    return json.loads(urllib.request.urlopen(req).read())

def call(path, body=None):
    if body is None:
        req = urllib.request.Request(f'{BASE}{path}', method='GET')
    else:
        req = urllib.request.Request(f'{BASE}{path}', data=json.dumps(body, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

sys.stdout.reconfigure(encoding='utf-8')

fixture = Path('fixtures/expenses_and_budget.xlsx')
u = upload(fixture)
fid = u['file_id']
print(f'Upload OK, file_id={fid}')

r = call('/api/plans', {'file_ids': [fid], 'request': '检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。'})
plan = r['plan']
kinds = [o['kind'] for o in plan['operations']]
print(f'Plan OK: kinds={kinds}, outputs={plan["outputs"]}')
print(f'  explanation: {plan["explanation"]}')

r = call('/api/executions', {'file_ids': [fid], 'plan': plan, 'confirmation_token': f"confirm:{plan['id']}"})
print(f'Exec OK: sheets={r["sheets"]}, conclusions={len(r["conclusions"])}')
for c in r['conclusions']:
    print(f'  [{c["severity"]}] {c["text"]} (step={c["source"]["step_id"]})')
print()
print('=== LLM MODE WORKS ===')