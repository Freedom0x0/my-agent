# 表析 Agent 技术方案 V2

> 审查自检: 2026-09-15
> 检查项: 细节到位 | 可验证 | 功能完善 | 用户体验 | 代码结构 | 高内聚低耦合 | 防腐层 | 边界处理

---

## 0. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 (对话式 UI + SheetJS 预览器)                           │
│  POST /api/chat { message, file_ids, session_id }           │
│  POST /api/files (upload)                                    │
│  GET  /api/outputs/{id} (download)                          │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP JSON
┌──────────────────────▼──────────────────────────────────────┐
│ 后端 FastAPI                                                 │
│                                                              │
│  ├── /api/files ────→ parser (inspect + store)              │
│  ├── /api/outputs ──→ FileResponse (stream)                 │
│                                                              │
│  ├── /api/chat ─────→ Agent Loop                             │
│  │     │                │                                    │
│  │     │       ┌───────▼────────┐                           │
│  │     │       │  Session Store  │ ← 会话上下文 (内存/SQLite)│
│  │     │       └────────────────┘                           │
│  │     │                │                                    │
│  │     │       ┌───────▼────────┐                           │
│  │     │       │  MiniMax API   │ ← Anthropic Messages API  │
│  │     │       │  (tool calling)│   带 tools 参数            │
│  │     │       └───────┬────────┘                           │
│  │     │               │ tool_use block                      │
│  │     │       ┌───────▼────────┐                           │
│  │     │       │  Tool Router   │ → 匹配 tablex_* handler   │
│  │     │       └───────┬────────┘                           │
│  │     │               │                                      │
│  │     │  ┌────────────▼─────────────────────────┐          │
│  │     │  │ Handler Layer (防腐层)                 │          │
│  │     │  │ 输入: tool_use JSON → 校验参数 → 调 executor  │          │
│  │     │  │ 输出: 结构化的 ToolResult JSON         │          │
│  │     │  └────────────┬─────────────────────────┘          │
│  │     │               │                                      │
│  │     │  ┌────────────▼─────────────────────────┐          │
│  │     │  │ Domain Layer (executor / parser)       │          │
│  │     │  │ 不变的领域逻辑、33 个测试已验证         │          │
│  │     │  └───────────────────────────────────────┘          │
│  │     │                                                      │
│  └─────┴──→ 循环直到 MiniMax 返回 text 或达到上限            │
│                                                              │
│  └── SQLite (文件元数据 + 输出记录 + 会话)                    │
└──────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **领域层不变** — executor.py / parser.py / operations.py 一行不改
2. **防腐层隔离** — handler 层负责 MiniMax JSON ↔ Python 领域对象 的双向转换
3. **Agent 自主调度** — MiniMax 决定工具调用顺序，不再有固定 pipeline
4. **Key 在服务端** — MiniMax API Key 只在后端
5. **审计不丢** — 每次工具调用触发 executor 的 AuditEvent，记录到会话

---

## 1. MiniMax 代理层（核心）

### 1.1 POST /api/chat

```json
// 请求
{
  "message": "帮我统一日期格式，去重，按部门汇总",
  "file_ids": ["file-uuid"],
  "session_id": "session-uuid-1234"
}

// 响应
{
  "reply": "处理完成！统一了日期和金额格式，按订单号去重删除了 2 行...",
  "tool_calls": [
    {"tool": "tablex_normalize", "status": "ok", "summary": "日期列 10 行格式统一"},
    {"tool": "tablex_normalize", "status": "ok", "summary": "金额列 8 行格式统一"},
    {"tool": "tablex_deduplicate", "status": "ok", "summary": "删除 2 行重复"},
    {"tool": "tablex_group_summary", "status": "ok", "summary": "3 个部门汇总完成"},
    {"tool": "tablex_export", "status": "ok", "output_id": "out-uuid"}
  ],
  "output_id": "out-uuid",
  "sheets": ["清洗后数据", "汇总结果", "问题清单", "_audit"]
}
```

### 1.2 Agent Loop 详细流程

```python
MAX_TOOL_CALLS = 15          # 单次用户消息最多工具调用次数
MAX_TOOL_CALL_SECONDS = 120  # 单次工具调用超时
MAX_SESSION_TOKENS = 16000   # 会话总 token 上限 (估算)
MAX_RESULT_BYTES = 4000       # 单次 tool_result 最大字节 (防 token 爆炸)

def process_chat(session_id: str, user_message: str, file_ids: list[str]):
    session = session_store.get_or_create(session_id)
    session.append_user_message(user_message)

    # 加锁防止同 session 并发
    with session.lock:
        for round_idx in range(MAX_TOOL_CALLS):
            # Token 检查，超限则截断最早的非关键消息
            session.messages = truncate_if_overflow(session.messages, MAX_SESSION_TOKENS)

            response = minimax_api.chat(
                model="MiniMax-Text-01",
                system=SYSTEM_PROMPT,
                messages=session.messages,
                tools=TABLEX_TOOL_DEFINITIONS,
                max_tokens=4096,
                temperature=0,
            )

            if response.stop_reason == "end_turn":
                reply = extract_text(response)
                session.append_assistant_message(reply)
                return build_response(reply, session.tool_calls_log)

            elif response.stop_reason == "tool_use":
                for block in response.content:
                    if block.type == "tool_use":
                        # 1. 参数校验（防腐层第一道）
                        validation = validate_tool_input(block.name, block.input, session)
                        if not validation.ok:
                            result = ToolResult(success=False, error=validation.error)
                        else:
                            # 2. 执行工具
                            try:
                                result = session.execute_tool(block.name, block.input)
                            except Exception as e:
                                result = ToolResult(success=False, error=str(e))

                        # 3. 截断超大结果
                        result_json = truncate_result(result, MAX_RESULT_BYTES)

                        # 4. 追加到对话上下文
                        session.messages.append({"role": "assistant", "content": [block]})
                        session.messages.append({"role": "user", "content": [{
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_json,
                        }]})

                        # 5. 失败时不回滚（见下方原子性说明）
                        session.record_tool_call(block.name, block.input, result)

            elif response.stop_reason == "max_tokens":
                return build_error("模型输出过长，请简化需求", "model_truncated")

    return build_error("处理步骤过多，请精简需求", "too_many_steps")
```

### 1.2.1 状态归属与处理流

**关键问题：`tables`（处理中的 DataFrame 状态）属于谁？**

```
Session (内存对象) 持有所有可变状态:
  ├── tables: {ref: DataFrame}        # 当前处理状态 (修改累加)
  ├── messages: list                  # MiniMax 对话历史
  ├── tool_calls_log: list            # 工具调用审计日志
  ├── lock: threading.Lock            # 并发锁
  └── output_dir: Path               #  最终输出目录 (runtime/outputs)

Tool Handler 接收 (session, input) → 直接修改 session.tables → 返回 ToolResult
```

工具调用流（一次循环）：
```
MiniMax → tool_use("tablex_normalize", {file_id, sheet, columns, type})
  ↓
handler.normalize(session, input)
  ↓
session.tables[ref] = _apply_normalize(session.tables[ref], ...)
  ↓
ToolResult(success=True, summary="已统一 3 列格式", data={"rows_changed": 5})
```

**关键：handler 不持有状态，所有数据存在 session 里**

### 1.2.2 原子性与失败处理

**原来 `execute_plan` 是原子的——失败就全部回滚**

新方案下：工具一个一个调用，部分失败怎么办？

| 失败场景 | 处理 |
|---------|------|
| 工具执行异常（pandas 报错） | 该工具返回 `success=False`，tables 不修改。MiniMax 看到错误可以重新规划 |
| 工具成功但 MiniMax 之后调错（基于错误前提） | 状态可能"半成品"，但每个工具都独立成功 |
| 用户中途刷新页面 | session 内存丢失，tables 状态丢失，需重新上传 + 重做 |
| 用户发"重做"指令 | 新建 session_id（旧 tables 丢弃），重新调工具 |

**接受"半成品"风险——原因：** 用户看到工具调用列表，可以清楚知道哪些成功了哪些失败。比回滚复杂逻辑更友好。

### 1.2.3 Session 持久化与恢复

**当前 session 状态分类：**

| 状态 | 存储位置 | 刷新后 |
|------|---------|--------|
| session_id | localStorage | 保留 |
| messages (对话) | SQLite `sessions` 表 | 保留 |
| files (上传文件元数据) | SQLite `files` 表 | 保留 |
| 原始上传文件 | `runtime/uploads/` | 保留 |
| tables (处理中 DataFrame) | **内存** | **丢失** |
| 最终 output_id | SQLite `outputs` 表 | 保留（如果之前调过 export） |

**恢复策略：**
```
页面刷新后:
  ↓
用 localStorage 里的 session_id 加载 messages + files
  ↓
显示历史对话（重新调 /api/chat 加载）
  ↓
如果用户问"接着刚才的" → 重新从原文件开始，重放所有 tool_calls
  ↓
或者：告诉用户"会话已过期，需要重新上传"
```

**简化方案：刷新即过期**——告诉用户刷新后需要重新开始。不实现复杂的状态恢复。

### 1.3 System Prompt

```text
你是表析 Agent，一个专业的中文 Excel 数据分析助手。

## 能力
你可以通过调用工具完成以下操作：
1. 读取和检查 Excel 文件
2. 统一数据格式（日期、数字）
3. 删除重复数据
4. 筛选符合条件的行
5. 按列分组汇总
6. 对比两个工作表的差异
7. 填充公式
8. 排序
9. 填充空值
10. 导出处理结果

## 工作流程
1. 用户上传文件后，自动调用 tablex_inspect 分析数据质量
2. 根据用户需求，组合调用工具完成处理
3. 最后调用 tablex_export 生成结果文件

## 规则
- 调用工具前确保 file_id 和 sheet 存在
- 每次调用一个工具，等待返回结果后再决定下一步
- 无法处理的请求（如图表、非 Excel 问题）明确告知用户
- 涉及删除/覆盖的操作，在回答中说明影响范围
- 使用中文回答，简洁清晰
```

### 1.4 边界处理

| 场景 | 处理 |
|------|------|
| MiniMax API 超时 | 重试 1 次（exponential backoff），仍失败返回 `model_timeout` |
| MiniMax 返回无效 tool_use (参数缺失) | 返回错误消息给 MiniMax 让它重新生成 |
| tool handler 执行异常 | 返回结构化错误 `{"success": false, "error": "..."}` 给 MiniMax |
| 超过最大工具调用次数 | 强制终止，返回 `too_many_steps` |
| 对话 Token 超限 | 丢弃最早的非关键轮次（保留系统提示和文件信息） |
| 用户输入非表格相关请求 | MiniMax 应回复"我目前只能处理 Excel 表格操作" |
| tool_result 内容过大 | 截断到 4000 字节，关键信息（success/summary/error）保留 |
| 同 session 用户重复发消息 | session.lock 串行化，拒绝并发请求 |
| tablex_inspect 返回数据过大 | 只返回字段级 summary，不返回全表 |

### 1.5 MiniMax 调用参数

```python
minimax_api.chat(
    model="MiniMax-Text-01",
    system=SYSTEM_PROMPT,           # 顶层参数，不是 messages
    messages=session.messages,
    tools=TABLEX_TOOL_DEFINITIONS,  # tool_use 工具定义
    max_tokens=4096,                # 单次响应最大 token
    temperature=0,                  # 确定性输出
    # 不使用 stream，第一版返回完整响应，简化错误处理
)
```

### 1.6 审计与溯源

每次工具调用记录：

```
sessions/{session_id}/
  ├── messages              # 对话历史
  ├── tool_calls_log        # 每个调用的输入+输出+结果摘要
  └── audit_events          # 映射到 executor 的 AuditEvent 列表
```

`tablex_export` 时：
- 把当前 session 的 `audit_events` 全部汇总
- 写入生成 xlsx 的隐藏 `_audit` Sheet
- 保留单次操作的影响行号、列、参数

**和原来一致：源文件 SHA-256 在 export 前校验不变 → 写审计到 _audit → 返回 output_id**

---

## 2. MCP 工具定义（防腐层设计）

### 2.1 代码结构

```
backend/app/mcp/
  __init__.py
  tools.py        # 工具定义 (Anthropic tool format JSON)
  schemas.py      # ToolCall / ToolResult 的 Pydantic 模型
  handlers.py     # 防腐层: tool_use → 参数校验 → 调 domain → ToolResult
  agent.py        # MiniMax 代理循环 (process_chat)
```

### 2.2 防腐层接口定义

```python
# schemas.py — 防腐层双向契约

class ToolCall(BaseModel):
    """MiniMax 发来的工具调用请求"""
    tool_use_id: str
    name: str
    input: dict[str, Any]

class ToolResult(BaseModel):
    """返回给 MiniMax 的结构化结果"""
    success: bool
    summary: str                          # 人类可读的摘要（中文），≤ 200 字
    data: dict[str, Any] | None = None    # 结构化数据（可选）
    error: str | None = None              # 错误信息

class ValidationResult(BaseModel):
    ok: bool
    error: str | None = None              # 校验失败的具体原因


def validate_tool_input(name: str, input: dict, session) -> ValidationResult:
    """防腐层第一道：参数校验（不进入领域层）"""
    handler = HANDLERS.get(name)
    if not handler:
        return ValidationResult(ok=False, error=f"未知工具: {name}")

    for field in handler.required_fields:
        if field not in input:
            return ValidationResult(ok=False, error=f"缺少参数: {field}")

    # 业务校验
    if name in {"tablex_normalize", "tablex_deduplicate", "tablex_filter",
                "tablex_group_summary", "tablex_fill_formula", "tablex_sort",
                "tablex_fill_null", "tablex_inspect"}:
        file_id = input.get("file_id")
        if not session.has_file(file_id):
            return ValidationResult(ok=False, error=f"文件不存在: {file_id}")

        if "sheet" in input:
            sheet = input["sheet"]
            sheet_ref = f"{file_id}::{sheet}"
            if sheet_ref not in session.tables:
                return ValidationResult(ok=False, error=f"工作表不存在: {sheet}")

    return ValidationResult(ok=True)


# handlers.py — 每个工具一个函数，输入 ToolCall → 输出 ToolResult

def handle_normalize(tool_call: ToolCall, session) -> ToolResult:
    """防腐层: 校验参数 → 调 executor → 封装结果"""
    try:
        file_id = tool_call.input["file_id"]
        sheet = tool_call.input["sheet"]
        columns = tool_call.input["columns"]
        target_type = tool_call.input["target_type"]

        sheet_ref = f"{file_id}::{sheet}"

        # 校验列存在
        missing = [c for c in columns if c not in session.tables[sheet_ref].columns]
        if missing:
            return ToolResult(success=False, error=f"列不存在: {missing}")

        # 调领域层
        df = session.tables[sheet_ref]
        new_df, affected = _apply_normalize(df, columns=columns, target_type=target_type)
        session.tables[sheet_ref] = new_df
        session.audit_events.append(make_audit_event(...))

        return ToolResult(
            success=True,
            summary=f"已统一 {len(columns)} 列格式，影响 {len(affected)} 行",
            data={"columns": columns, "affected_rows": affected[:20]},
        )
    except KeyError as e:
        return ToolResult(success=False, error=f"缺少参数: {e}")
    except Exception as e:
        return ToolResult(success=False, error=f"执行失败: {str(e)[:200]}")


# 结果截断（防 token 爆炸）
MAX_RESULT_BYTES = 4000

def truncate_result(result: ToolResult, max_bytes: int) -> str:
    """截断过大的 tool_result，控制 token 使用"""
    text = result.model_dump_json(exclude_none=True)
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    # 优先保留 summary/error，截断 data
    return json.dumps({
        "success": result.success,
        "summary": result.summary,
        "error": result.error,
    }, ensure_ascii=False)
```

### 2.3 11 个工具定义

每个工具定义包含：name + description + input_schema + handler。

| 工具 | description | 关键参数 | 返回 summary 示例 |
|------|------------|---------|-------------------|
| `tablex_upload` | 上传 Excel/CSV 文件并检测数据质量问题 | file(bytes) | "已上传，发现 4 个数据质量问题" |
| `tablex_inspect` | 分析指定文件的数据质量问题 | file_id | "日期列存在多种格式，发现 2 行重复" |
| `tablex_normalize` | 统一指定列的格式（数字/日期/文本） | file_id, sheet, columns[], target_type | "已统一 3 列的格式" |
| `tablex_deduplicate` | 按指定列删除重复行 | file_id, sheet, key_columns[], keep | "删除 2 行重复数据" |
| `tablex_filter` | 筛选符合条件的行并写入新 Sheet | file_id, sheet, conditions[], output_sheet | "筛选出 5 条记录" |
| `tablex_group_summary` | 分组汇总并写入新 Sheet | file_id, sheet, group_by[], metrics{}, output_sheet | "3 个部门汇总完成" |
| `tablex_compare` | 对比两个工作表差异 | left_ref, right_ref, key_columns[] | "新增 2 条、删除 1 条、变化 3 条" |
| `tablex_fill_formula` | 空白单元格补公式 | file_id, sheet, target_column, expression, range | "已补充 5 个公式" |
| `tablex_sort` | 按指定列排序 | file_id, sheet, column, order | "已按金额降序排列" |
| `tablex_fill_null` | 填充空值 | file_id, sheet, column, method | "已填充 3 个空值" |
| `tablex_export` | 生成处理后的 xlsx 文件并返回下载 ID | file_id | "已生成处理结果" |

### 2.4 Tool Call Result 格式

```json
// 成功响应
{
  "success": true,
  "summary": "已删除 2 行重复数据",
  "data": {
    "removed_rows": [3, 5],
    "input_rows": 10,
    "output_rows": 8,
    "columns_affected": ["订单号"]
  }
}

// 失败响应
{
  "success": false,
  "summary": "处理失败",
  "error": "列 '订单号' 不存在于工作表 '收支明细'"
}
```

### 2.5 会话上下文管理

```python
# session/session.py
# 每个 session 包含:
{
  "session_id": str,
  "files": {file_id: {"path": Path, "inspection": dict}},
  "tables": {ref: DataFrame},       # 当前处理状态（内存中）
  "output_id": str | None,          # 当前结果
  "messages": list,                 # MiniMax 对话历史
  "created_at": datetime,
  "updated_at": datetime
}
```

- 会话存储用 SQLite (`sessions` 表)
- 每个 session 的 `tables` 存内存（因为 DataFrame 不适合序列化）
- 会话 30 分钟无操作自动过期
- 文件清理：会话过期后清理临时文件

---

## 3. 前端交互

### 3.1 组件树与职责

```
App
├── AppHeader (标题 + 操作按钮)
├── FileUploader (拖拽/点击, onDragOver / onDrop / onChange)
│   └── FileCard (已上传文件卡片, 删除按钮)
├── SpreadsheetPreview (SheetJS 解析 + 渲染)
│   ├── SheetTabs (工作表标签, 点击切换)
│   └── TableView (数据表格, 横向/纵向滚动, 表头固定)
├── ChatPanel
│   ├── ChatHistory (消息列表, 自动滚动到底部)
│   │   ├── ChatBubble (用户消息)
│   │   └── ChatBubble (Agent 回复)
│   │       ├── ToolCallCard (工具调用结果, 绿色/红色标签)
│   │       └── ConclusionSummary (结论摘要)
│   └── ChatInput
│       ├── PromptChips (推荐 prompt, 点击填充)
│       ├── TextArea (输入框, 1000 字限制)
│       └── SendButton (发送, loading 态)
└── DownloadButton (浮动, 指向 /api/outputs/{id})
```

### 3.2 状态管理

```typescript
// domain/models.ts

type AppStatus = "idle" | "uploading" | "processing" | "completed" | "error";

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: ToolCallResult[];
  timestamp: number;
};

type SessionState = {
  status: AppStatus;
  files: FileItem[];
  messages: ChatMessage[];
  currentPreview: WorkbookData | null;  // SheetJS 解析后的 workbook
  resultOutputId: string | null;
  error: UserFacingError | null;
};
```

### 3.3 前端防腐层

```
api/                 ← HTTP 层：contracts (Zod) + httpClient
  contracts.ts       ← /api/chat 请求/响应 schema
  httpClient.ts      ← fetch 封装 (不变)
domain/              ← 前端领域模型
  models.ts          ← SessionState, ChatMessage, FileItem 等
  workflow.ts        ← reducer (不变)
hooks/               ← 业务逻辑
  useWorkflow.ts     ← 状态管理 (新增 session 字段)
  useChat.ts         ← 新增: /api/chat 调用 + 流式处理
  useSpreadsheet.ts  ← 新增: SheetJS 封装
components/          ← 纯展示
  FileUploader/
  SpreadsheetPreview/
  ChatPanel/
    ChatBubble/
    ChatInput/
  DownloadButton/
```

**防腐规则：** components 只能通过 hooks 获取数据，hooks 调 api/，api/ 里的 contracts 用 Zod 校验后端响应。和现有规则一致。

### 3.4 前端边界处理

| 场景 | 处理 |
|------|------|
| 上传中再次拖拽 | 忽略，提示"正在上传" |
| 文件 > 25MB | 前端先检查文件大小，超限直接提示不上传 |
| 非 .xlsx/.xls/.csv | accept 属性 + 前端二次校验 |
| 正在处理时用户发消息 | 按钮 disabled，提示"正在处理" |
| 预览区加载中 | Skeleton 动画 |
| SheetJS 解析失败 | 显示"无法预览该文件格式" |
| 对话历史过长 | 虚拟列表（前 50 条）|
| 页面刷新 | session_id 存 localStorage，刷新后恢复对话但不恢复表格内存状态 |
| 下载失败 | 错误提示 + 重试按钮 |

---

## 4. 实施步骤

### Step 1: 后端 MCP 层 (2-3 天)

**新增文件:**
- `backend/app/mcp/__init__.py`
- `backend/app/mcp/tools.py` — 11 个 tool 定义的 JSON
- `backend/app/mcp/schemas.py` — ToolCall, ToolResult Pydantic 模型
- `backend/app/mcp/handlers.py` — 11 个 handler 函数（防腐层）
- `backend/app/mcp/agent.py` — Agent loop（process_chat）
- `backend/app/mcp/session.py` — 会话管理（创建/恢复/过期）
- `backend/app/api/chat.py` — POST /api/chat 路由
- `backend/app/domain/executor.py` — 新增 sort / fill_null 逻辑

**新增测试:**
- `backend/tests/test_tools.py` — 每个 handler 的单元测试
- `backend/tests/test_agent.py` — Agent loop 测试（mock MiniMax）
- `backend/tests/test_session.py` — 会话管理测试

### Step 2: SheetJS 预览器 (1 天)

- `frontend/src/components/SpreadsheetPreview.tsx`
- `frontend/src/components/SheetTabs.tsx`
- `frontend/src/hooks/useSpreadsheet.ts`
- 更新 `styles.css`

### Step 3: 前端交互改造 (2 天)

- 重写 `App.tsx` → 对话式布局
- 新建 `ChatBubble.tsx`, `ChatInput.tsx`, `FileUploader.tsx`
- 新建 `hooks/useChat.ts`
- 重写 `ResultPanel.tsx` → 嵌入到对话气泡
- 删除旧组件: `InspectionPanel`, `PlanPanel`, `TaskPanel`, `FilePanel`
- 更新 `domain/models.ts`, `domain/workflow.ts`
- 更新 `styles.css`

### Step 4: 测试 + 集成 (1 天)

- 后端全长测试：upload → chat → tool calls → export → download
- 前端测试适配
- 端到端手动验证

---

## 5. 验证方案

### 后端验证
```bash
python -m pytest backend/tests/ -q           # 33 个旧测试全通过
python -m pytest backend/tests/test_tools.py -q  # 新工具测试通过
python -m pytest backend/tests/test_agent.py -q   # Agent loop 测试通过
```

### 前端验证
```bash
npm run build --prefix frontend               # 无 TS 错误
npm run test --prefix frontend -- --run         # 测试通过
```

### 手动验证场景

| 场景 | 步骤 | 预期 |
|------|------|------|
| 上传+预览 | 拖拽 expenses.xlsx | 预览区展示表格，Sheet 可切换，问题提示显示 |
| 基础对话 | 输入"检查数据问题" | Agent 调 inspect，返回数据质量报告 |
| 清洗+汇总 | 输入"统一格式，去重，按部门汇总" | Agent 调 normalize → deduplicate → group_summary → export |
| 高风险确认 | 输入"删掉所有空行" | Agent 回答中说明影响行数 |
| 多轮对话 | 完成后输入"再按类别统计一下" | Agent 继续处理，不需要重新上传 |
| 排序 | 输入"按金额从大到小排序" | Agent 调 sort 工具 |
| 错误输入 | 输入"给我写首诗" | Agent 回复不支持 |
| 非 Excel 文件 | 上传 txt 文件 | 前端拒绝上传，提示格式要求 |

---

## 6. 不做的（当前版本）

- Word/PDF 预览
- 图表生成
- 在线编辑
- 用户系统
- 数据透视表
- 外部 MCP 服务集成

---

## 7. 删除/停用的旧代码

- `backend/app/llm/` — DemoPlanner、CompatiblePlanner、base.py 不再使用（移入 `_archive/`）
- `backend/app/domain/operations.py` — 操作 DSL 的 validate_plan 等不再使用（executor 被 handler 直接调，不走 plan 校验）
- `frontend/src/components/InspectionPanel.tsx` — 合并入预览
- `frontend/src/components/PlanPanel.tsx` — 不再需要
- `frontend/src/components/TaskPanel.tsx` — 合并入 ChatInput
- `frontend/src/hooks/usePlan.ts` — 不再需要

保留：`executor.py`、`parser.py`、`audit.py`、`schemas.py`（OperationPlan 等模型可能还被其他模块引用，先保留，后续清理）