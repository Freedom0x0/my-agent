# 表析 Agent 详细技术设计

## 0. 文档用途与执行规则

本文档是“表析 Agent”第一版的实现基线，供编码 Agent 直接执行。实现者必须优先遵守本文档中的接口、字段名、状态值、错误码和安全边界；高层产品描述见 `docs/superpowers/specs/2026-09-13-excel-analysis-agent-design.md`，两者冲突时以本文档为准。

第一版目标是完成一个可本地运行、可在线部署、可以真实上传并处理 Excel 的 Web 应用。用户上传 Excel/CSV，输入自然语言任务，系统生成结构化操作计划，用户确认后由确定性执行器生成新的 `.xlsx` 文件，并展示结论、问题和数据来源。

实现 Agent 必须遵守以下顺序：

1. 先读取本文档完整内容。
2. 先实现后端领域模型、解析器、操作校验和执行器，再接 API 与前端。
3. 每完成一个模块，先运行该模块的测试，再继续下一个模块。
4. 不改变本文档规定的 API 路径、JSON 字段名、操作 `kind` 和错误码；确需变更时，必须先同步修改本文档和所有相关测试。
5. 不让大模型直接生成或执行 Python、Shell、SQL 或文件路径操作。
6. 不覆盖源文件；所有写操作必须生成新工作簿。

## 1. 非目标与固定范围

### 1.1 第一版必须支持

- `.xlsx` 文件读取与生成。
- `.xls` 文件读取，结果统一生成 `.xlsx`。
- `.csv` 文件读取，内部视为一个名为“数据”的工作表，结果生成 `.xlsx`。
- 单文件和多文件任务。上传接口一次接收一个文件，前端循环调用上传接口，多文件任务在计划和执行接口中提交多个 `file_id`。
- 多工作表工作簿。
- 数据体检、格式标准化、去重、筛选、分组汇总、多表对比、补公式、问题清单。
- 结论卡片、前后指标、来源追溯和结果文件下载。

### 1.2 第一版明确不支持

- Word、PDF、图片和扫描件解析。
- OCR。
- Excel 宏、VBA、外部链接、透视表对象和嵌入脚本的执行或完整保留。
- 在线多人协作编辑。
- 用户账号、权限、计费和组织管理。
- 任意 Python 代码执行。
- 大文件异步任务队列。第一版对中小型文件采用同步执行，但保留任务状态字段。

## 2. 总体架构

第一版使用模块化单体架构。前端是 React 静态应用，后端是一个 FastAPI 服务，SQLite 保存元数据，文件保存在应用目录。领域模块之间通过 Python 类型和函数接口通信，不通过隐式全局变量通信。

```text
Browser
  |
  | React + TypeScript, JSON, multipart/form-data
  v
Nginx or Vite dev proxy
  |
  v
FastAPI application
  +-- API routes
  +-- Workflow service
  +-- Planner adapter
  +-- Operation validator
  +-- Workbook parser
  +-- Deterministic executor
  +-- Audit and output validator
  |
  +-- SQLite metadata database
  +-- runtime/uploads
  +-- runtime/outputs
  +-- OpenAI-compatible model API (optional)
```

### 2.1 模块边界

| 模块 | 责任 | 不负责 |
|---|---|---|
| `parser` | 读取文件、识别表头、推断字段、发现数据问题 | 修改文件、调用模型 |
| `operations` | 定义和校验操作 DSL、判断确认要求 | 读取用户上传文件 |
| `executor` | 按已校验计划执行确定性数据处理、生成工作簿 | 理解自然语言、执行任意代码 |
| `audit` | 记录步骤、影响行、计算口径和来源 | 生成未经计算验证的结论 |
| `llm` | 将自然语言和表格画像转换成 `OperationPlan` | 直接读写本地路径、直接执行操作 |
| `service` | 编排解析、规划、执行和结果校验 | 处理 HTTP 细节 |
| `api` | 参数校验、文件存取、状态码和响应序列化 | 实现表格算法 |
| `frontend` | 上传、任务输入、计划确认、结果展示和下载 | 保存模型密钥、修改 Excel |

### 2.2 推荐目录

```text
backend/
  __init__.py
  app/
    __init__.py
    main.py
    config.py
    schemas.py
    api/
      __init__.py
      routes.py
    domain/
      __init__.py
      parser.py
      operations.py
      executor.py
      audit.py
      service.py
    llm/
      __init__.py
      base.py
      demo.py
      compatible.py
  tests/
    conftest.py
    test_health.py
    test_parser.py
    test_operations.py
    test_executor.py
    test_service.py
    test_api.py
    test_end_to_end.py
frontend/
  src/
    main.tsx
    App.tsx
    styles.css
    api/
      httpClient.ts
      contracts.ts
      fileApi.ts
      planApi.ts
      executionApi.ts
      mappers.ts
    domain/
      models.ts
      workflow.ts
    hooks/
      useWorkflow.ts
      useUpload.ts
      usePlan.ts
      useExecution.ts
    components/
      primitives/
      feedback/
      layout/
      FilePanel.tsx
      TaskPanel.tsx
      InspectionPanel.tsx
      PlanPanel.tsx
      ResultPanel.tsx
    __tests__/
      App.test.tsx
    test/setup.ts
  package.json
  tsconfig.json
  vite.config.ts
  vitest.config.ts
fixtures/
  personnel_messy.xlsx
  project_progress_messy.xlsx
  expenses_and_budget.xlsx
scripts/
  create_fixtures.py
runtime/
  uploads/
  outputs/
docs/
  demo-script.md
```

### 2.3 多文件引用规则

解析结果内部使用 `SheetRef` 标识工作表，格式固定为 `<file_id>::<sheet_name>`。计划中的 `source_sheets`、`sheet`、`left_sheet` 和 `right_sheet` 始终使用完整 `SheetRef`，避免不同文件存在同名工作表时产生歧义；单文件任务也不使用裸工作表名。

例如：`file-001::明细` 和 `file-002::明细` 是两个不同的工作表。服务层在调用 Planner 前负责构造完整引用，执行器只接受已经解析并验证过的 `SheetRef`。

## 3. 技术选型与运行配置

### 3.1 固定技术选型

- Python 3.11 或更高版本。
- FastAPI + Uvicorn。
- Pydantic v2 + pydantic-settings。
- pandas 用于读取、类型转换、分析和数据框操作。
- openpyxl 用于 `.xlsx` 工作簿生成、公式写入和输出校验。
- xlrd 用于读取 `.xls`。
- SQLite 使用 Python 标准库 `sqlite3`，第一版不引入 ORM。
- React + TypeScript + Vite。
- Vitest + Testing Library + jsdom 用于前端测试。
- 模型通过 OpenAI 兼容 HTTP API 接入；第一版不得让前端直接请求模型。

### 3.2 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_MODE` | `demo` | `demo` 使用内置规划器，`llm` 使用模型适配器 |
| `APP_HOST` | `0.0.0.0` | FastAPI 监听地址 |
| `APP_PORT` | `8000` | FastAPI 监听端口 |
| `APP_DATA_DIR` | `runtime` | 上传和输出根目录 |
| `MAX_UPLOAD_BYTES` | `26214400` | 25 MiB |
| `MODEL_BASE_URL` | 空 | OpenAI 兼容接口地址 |
| `MODEL_API_KEY` | 空 | 只在后端读取 |
| `MODEL_NAME` | 空 | 模型名称 |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔的前端来源 |
| `VITE_API_BASE_URL` | `/api` | 前端构建时使用的后端 API 前缀，只允许相对路径或配置的 HTTPS 来源 |

`APP_MODE=demo` 时不要求模型相关变量存在。`APP_MODE=llm` 且模型配置不完整时，服务可以启动，但规划接口必须返回稳定的 `model_not_configured` 错误，而不能回退到任意未声明的模型。

### 3.3 依赖要求

后端运行依赖至少包括：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`pandas`、`openpyxl`、`xlrd`、`python-multipart`、`httpx`。

后端测试依赖至少包括：`pytest`、`pytest-cov`。

前端运行依赖至少包括：`react`、`react-dom`、`zod`。

前端开发依赖至少包括：`typescript`、`vite`、`@vitejs/plugin-react`、`vitest`、`jsdom`、`@testing-library/react`、`@testing-library/jest-dom`、`@testing-library/user-event`。

## 4. 领域数据模型

所有后端对外和模块间数据模型使用 Pydantic。日期时间使用 ISO 8601 字符串；行号使用从 1 开始的 Excel 行号；金额等数值在 JSON 中使用 number，不使用格式化字符串。

### 4.1 表格体检模型

```python
class ColumnInspection(BaseModel):
    name: str
    inferred_type: Literal["text", "number", "date", "boolean", "mixed", "empty"]
    null_count: int
    unique_count: int
    sample_values: list[str] = Field(default_factory=list, max_length=5)


class DataIssue(BaseModel):
    code: Literal[
        "blank_header",
        "null_values",
        "duplicate_rows",
        "mixed_numeric",
        "mixed_date",
        "empty_sheet",
        "reserved_column",
    ]
    severity: Literal["info", "warning", "error"]
    message: str
    sheet: str
    column: str | None = None
    rows: list[int] = Field(default_factory=list, max_length=200)


class SheetInspection(BaseModel):
    name: str
    row_count: int
    column_count: int
    columns: list[ColumnInspection]
    preview: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    issues: list[DataIssue] = Field(default_factory=list)
    formula_count: int = 0


class WorkbookInspection(BaseModel):
    filename: str
    file_type: Literal["xlsx", "xls", "csv"]
    sheets: list[SheetInspection]
```

服务层必须额外维护：

```python
class SheetRef(BaseModel):
    file_id: str
    sheet_name: str
    ref: str  # exactly "<file_id>::<sheet_name>"
```

`WorkbookInspection` 保留原文件内的工作表名；`SheetRef` 只在多文件任务的规划、执行和审计上下文中使用。编码实现可以将 `source_sheets: list[str]` 中的字符串解析为 `SheetRef.ref`，但不能使用模糊的裸工作表名匹配多个文件。

保留内部列名前缀 `__tablex_`，用户上传的表头如果以该前缀开头，必须产生 `reserved_column` 错误并拒绝执行写操作。

### 4.2 操作模型

操作计划的 `operations` 使用 Pydantic discriminated union，判别字段是 `kind`。下面是逻辑定义；实现时字段名必须保持一致。

```python
class NormalizeOperation(BaseModel):
    kind: Literal["normalize"]
    sheet: str
    columns: list[str] = Field(min_length=1)
    target_type: Literal["number", "date", "text"]


class DeduplicateOperation(BaseModel):
    kind: Literal["deduplicate"]
    sheet: str
    key_columns: list[str] = Field(min_length=1)
    keep: Literal["first", "last"] = "first"


class FilterCondition(BaseModel):
    column: str
    operator: Literal[
        "eq", "ne", "contains", "gt", "gte", "lt", "lte",
        "is_null", "not_null", "in"
    ]
    value: str | int | float | bool | list[str | int | float] | None = None


class FilterOperation(BaseModel):
    kind: Literal["filter"]
    sheet: str
    conditions: list[FilterCondition] = Field(min_length=1)
    match: Literal["all", "any"] = "all"
    output_sheet: str = "筛选结果"


class GroupSummaryOperation(BaseModel):
    kind: Literal["group_summary"]
    sheet: str
    group_by: list[str] = Field(min_length=1)
    metrics: dict[str, list[Literal["sum", "mean", "count", "min", "max"]]]
    output_sheet: str = "汇总结果"


class CompareOperation(BaseModel):
    kind: Literal["compare"]
    left_sheet: str
    right_sheet: str
    key_columns: list[str] = Field(min_length=1)
    compare_columns: list[str] | None = None
    output_sheet: str = "对比结果"


class FillFormulaOperation(BaseModel):
    kind: Literal["fill_formula"]
    sheet: str
    target_column: str
    expression: str
    start_row: int = Field(ge=2)
    end_row: int = Field(ge=2)
    only_blank: bool = True


class CreateIssueSheetOperation(BaseModel):
    kind: Literal["create_issue_sheet"]
    output_sheet: str = "问题清单"
    issue_codes: list[str] | None = None


Operation = Annotated[
    NormalizeOperation
    | DeduplicateOperation
    | FilterOperation
    | GroupSummaryOperation
    | CompareOperation
    | FillFormulaOperation
    | CreateIssueSheetOperation,
    Field(discriminator="kind"),
]


class OperationPlan(BaseModel):
    id: str
    source_sheets: list[str] = Field(min_length=1)
    operations: list[Operation] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    explanation: str
    clarification_question: str | None = None
    requires_confirmation: bool = False
```

`normalize` 和 `deduplicate` 是对内存中的工作表流水线进行变换的操作，按 `operations` 顺序累积生效；它们不单独创建工作表。执行结束后，如果 `outputs` 包含 `清洗后数据`，就把经过这些变换的主工作表写入该名称；如果计划没有该名称，则把变换结果写入 `outputs[0]`。第一版要求涉及变换操作的单文件计划必须包含至少一个清洗数据输出名称，避免清洗结果只存在于内存中。

`filter`、`group_summary`、`compare` 使用各自的 `output_sheet` 写入新工作表。`create_issue_sheet` 使用其 `output_sheet` 写入问题清单。计划中的 `outputs` 必须包含这些操作声明的输出名称；服务端校验不一致时返回 `invalid_plan`。

`requires_confirmation` 是服务端根据操作重新计算的派生字段。模型提供该字段时，服务端必须重新计算，不得因为模型返回 `false` 就跳过确认。

### 4.3 审计与执行结果模型

```python
class AuditEvent(BaseModel):
    step_id: str
    operation: str
    input_sheets: list[str]
    output_sheets: list[str]
    columns: list[str] = Field(default_factory=list)
    input_rows: int
    output_rows: int
    affected_rows: list[int] = Field(default_factory=list, max_length=200)
    details: dict[str, Any] = Field(default_factory=dict)


class ConclusionSource(BaseModel):
    step_id: str
    sheet: str
    columns: list[str] = Field(default_factory=list)
    condition: str | None = None
    formula: str | None = None
    rows: list[int] = Field(default_factory=list, max_length=200)


class Conclusion(BaseModel):
    text: str
    value: str | int | float | None = None
    severity: Literal["info", "warning", "error"] = "info"
    source: ConclusionSource


class ExecutionResult(BaseModel):
    output_id: str
    output_path: str
    sheets: list[str]
    metrics: dict[str, int | float | str]
    conclusions: list[Conclusion]
    audit_events: list[AuditEvent]
```

## 5. 文件解析器设计

### 5.1 公共接口

```python
def inspect_workbook(path: Path) -> WorkbookInspection:
    """Read one supported file and return a bounded table inspection."""


def load_tables(path: Path) -> dict[str, pd.DataFrame]:
    """Load normalized tables with an internal source-row column."""
```

`load_tables` 只供领域服务和执行器使用。返回的 DataFrame 必须含内部列 `__tablex_source_row__`，其值为原始 Excel 行号；写出用户结果前必须移除该列。

### 5.2 文件类型处理

- 扩展名统一转小写。
- `.xlsx` 使用 pandas/openpyxl。
- `.xls` 使用 pandas/xlrd。
- `.csv` 依次尝试 `utf-8-sig`、`utf-8`、`gb18030`；失败时返回 `unsupported_encoding`。
- CSV 使用 `csv.Sniffer` 在逗号、制表符和分号中识别分隔符；无法确定时使用逗号。
- `.xlsx` 文件头必须符合 ZIP 文件签名 `PK`; `.xls` 文件头必须符合 OLE Compound File 签名；CSV 必须能按文本读取。文件头不匹配时返回 `unsupported_file`。
- 扩展名不在白名单中时抛出 `UnsupportedFileError`，错误码为 `unsupported_file`。
- 文件不存在时抛出 `FileNotFoundError`，由 API 转成 `file_not_found`。

### 5.3 表头识别

读取时先使用 `header=None`，保留原始单元格值。对前 20 行执行：

1. 找到第一行非空单元格数量至少为 2 的行。
2. 该行作为表头。
3. 表头值转字符串并去除首尾空白。
4. 空表头命名为 `未命名列1`、`未命名列2`，并产生 `blank_header`。
5. 重复表头追加 `_2`、`_3` 等后缀。
6. 表头和数据行以下的完全空行丢弃，其他行保留。
7. 没有可用表头时返回 `empty_sheet`，该工作表 `row_count=0`。

不自动把第一行以外的标题、说明或合并单元格内容当作数据；表头探测最多只看前 20 行，超过范围需要返回明确的解析提示。

### 5.4 类型推断与问题识别

每列进行以下检测：

- `null_count`：空字符串、空白字符串和 pandas NA 都计为空。
- 数字探针：移除逗号、货币符号和末尾常见单位后尝试转数值。
- 日期探针：尝试 ISO、`YYYY/MM/DD`、`YYYY-MM-DD`、`YYYY年M月D日` 和 pandas 可识别日期。
- 若同列同时出现可转换数字和不可转换文本，产生 `mixed_numeric`。
- 若同列存在两种以上日期表示格式，产生 `mixed_date`。
- 重复整行产生 `duplicate_rows`，行号使用 `__tablex_source_row__`。
- 任意列存在空值产生 `null_values`，最多记录前 200 个行号。
- 用户列名以 `__tablex_` 开头产生 `reserved_column`，severity 为 `error`。

类型推断优先级为：全空 `empty`，全为布尔 `boolean`，全为日期 `date`，全为数值 `number`，全为文本 `text`，否则 `mixed`。

### 5.5 预览约束

每个工作表最多返回 20 行预览，每行最多返回已识别的列。预览只用于前端展示和模型规划，不作为执行器的计算输入。所有真实计算必须重新读取完整工作表。

## 6. 操作 DSL 与执行语义

### 6.1 通用校验

执行前必须完成：

1. `source_sheets` 中每个工作表存在。
2. 每个操作引用的工作表存在。
3. 每个操作引用的列存在。
4. 输出工作表名称去除首尾空白、非空、长度不超过 31 个字符，且不能是 `_audit`。
5. 同一计划中的输出工作表名称不能重复。
6. 计划中不能包含未知 `kind`。
7. 不能引用内部列 `__tablex_source_row__`。
8. 所有高影响操作都使 `requires_confirmation=True`。

校验失败抛出 `InvalidPlanError`，由 API 转成 `invalid_plan`。

### 6.2 `normalize`

用途：将指定列转换为统一类型。

- `number`：去除逗号、货币符号、空白和末尾中文金额单位；无法转换的非空值保留原值并写入问题清单。
- `date`：转换为日期对象，输出格式为 `YYYY-MM-DD`；无法转换的非空值保留原值并写入问题清单。
- `text`：转换为字符串并去除首尾空白；空值仍为空。
- `affected_rows` 只记录值发生变化的源行号。
- `normalize` 本身不需要确认，但如果同一计划包含高影响操作，整个计划仍需确认。

### 6.3 `deduplicate`

用途：按 `key_columns` 去重，默认保留第一次出现的记录。

- `keep=first` 使用 pandas `drop_duplicates(keep="first")`。
- `keep=last` 使用 `drop_duplicates(keep="last")`。
- key 任意为空的行不得互相删除；这些行保留并写入问题清单。
- `affected_rows` 记录被移除记录的源行号。
- 该操作始终是高影响操作，必须使用 `confirm:<plan.id>`。

### 6.4 `filter`

用途：筛选记录并将结果写入新工作表。

条件含义：

- `eq` / `ne`：标准化字符串后比较，数字优先按数字比较。
- `contains`：字符串包含，大小写不敏感。
- `gt` / `gte` / `lt` / `lte`：数值或日期比较，无法转换的值视为不匹配。
- `is_null` / `not_null`：忽略 `value`。
- `in`：与列表任一值匹配。
- `match=all` 对所有条件取 AND，`match=any` 取 OR。

原始数据不删除，筛选结果写入 `output_sheet`。该操作不需要确认。

### 6.5 `group_summary`

用途：分组统计并生成新工作表。

- `group_by` 是一个或多个列。
- `metrics` 的 key 必须是数值列或可转换为数值的列。
- `sum`、`mean`、`min`、`max` 对无法转换的值忽略，并在问题清单记录。
- `count` 统计非空值数量。
- 输出列命名为 `<原列>_<聚合名>`，例如 `金额_sum`、`金额_mean`。
- 分组空值显示为 `未填写`。
- 输出按 `group_by` 字典序排序，保证结果可复现。
- 计算结果必须由执行器生成，模型不得提供指标数值。

### 6.6 `compare`

用途：比较两个工作表按 key 的记录变化。

- `left_sheet` 和 `right_sheet` 可以来自同一工作簿或计划中的不同文件；服务层负责把不同文件的表名映射成唯一引用。
- `key_columns` 在两个工作表中都必须存在。
- key 组合必须唯一；一侧有重复 key 时，返回 `duplicate_compare_key` 的 `invalid_plan`，不猜测如何合并。
- `compare_columns=null` 时比较两侧除 key 外的所有共同列。
- 输出至少包含 `变化类型`、key 列、`变化字段`、`左侧值`、`右侧值`。
- 变化类型只能是 `added`、`removed`、`changed`。
- 只在至少一列值不同的情况下产生 `changed`。
- 输出排序为变化类型固定顺序 `added`、`removed`、`changed`，再按 key 排序。

### 6.7 `fill_formula`

用途：在指定行范围内补充目标列公式。

`expression` 使用列名占位符和 `{row}` 行占位符，例如：

```text
={数量}{row}*{单价}{row}
```

执行器将其转换成 Excel 公式，例如 `=C2*D2`。

- 允许列名占位符、`{row}`、数字、小数点、空格、括号、`+ - * /` 和白名单函数 `ROUND`、`SUM`、`IF`。
- 禁止 `!`、`[ ]`、`:`、引号、宏函数、外部工作簿引用和换行。
- `start_row <= end_row`，范围必须在实际工作表数据范围内。
- `only_blank=true` 时只填充目标单元格为空的行。
- `only_blank=false` 仍必须确认，并可覆盖目标单元格。
- 该操作始终是高影响操作，必须确认。
- `affected_rows` 记录真正写入公式的源行号。

### 6.8 `create_issue_sheet`

用途：将解析阶段和执行阶段的问题写入新工作表。

列固定为：`问题级别`、`问题类型`、`工作表`、`字段`、`行号`、`问题描述`、`处理状态`。

`处理状态` 只能是 `未处理`、`已修复`、`仅提示`。问题清单本身不修改源数据，不需要确认。

## 7. 确认、执行与输出规则

### 7.1 高影响操作

以下操作属于高影响：

- `deduplicate`。
- `fill_formula`。
- 任何未来加入的 `overwrite=true` 操作。

计划的确认令牌只接受精确字符串：`confirm:<plan.id>`。缺失或不匹配时抛出 `ConfirmationRequired`，API 返回 HTTP 409 和 `confirmation_required`。

### 7.2 执行流程

```text
读取源文件
  -> 加载所有工作表和源行号
  -> 校验计划
  -> 校验确认令牌
  -> 按 operations 顺序执行
  -> 生成问题清单
  -> 写入新工作簿
  -> 写入隐藏 _audit 工作表
  -> 重新打开输出文件
  -> 校验工作表、行数、公式和文件可读性
  -> 生成结论与 ExecutionResult
```

### 7.3 输出工作簿布局

输出文件命名为 `<原文件名>_表析结果_<output_id前8位>.xlsx`，实际保存路径由服务端生成。

工作表顺序固定为：

1. `原始_<文件ID前8位>_<源工作表>`：源数据快照，移除内部列但不做数据清洗。
2. 计划要求的清洗和结果工作表。
3. `问题清单`，如果计划包含 `create_issue_sheet` 或存在问题。
4. `_audit`，设置为 hidden。

工作表名称超过 Excel 31 字符限制时，执行器必须生成稳定的截断名称并确保唯一，不能静默覆盖其他工作表。

输出名称映射是确定性的：

- 变换操作的主工作表输出名称为 `清洗后数据`；没有该名称时使用 `outputs[0]`。
- `FilterOperation.output_sheet`、`GroupSummaryOperation.output_sheet`、`CompareOperation.output_sheet` 和 `CreateIssueSheetOperation.output_sheet` 必须原样作为目标名称，经过 Excel 名称校验后写入。
- 同一工作表名若由两个操作产生，计划校验失败，不自动追加后缀。
- `原始_<文件ID前8位>_<源工作表>` 的名称只用于源快照；如果名称超过 31 字符，按“截断到 24 字符 + `_` + 6 位稳定哈希”生成。

### 7.4 输出校验

写入后必须使用 openpyxl 重新打开输出文件并检查：

- 文件可以打开。
- 每个计划输出工作表存在。
- 每个计划输出工作表不是意外空表。
- 公式数量与 `fill_formula` 的实际写入数量一致。
- 审计记录中的输入/输出行数与实际结果一致。
- 源文件 SHA-256 与执行前相同。

应用启动时必须创建 `APP_DATA_DIR`、`APP_DATA_DIR/uploads`、`APP_DATA_DIR/outputs` 和 SQLite 父目录；目录已存在时保持其中已有文件，不删除用户数据。

校验失败抛出 `OutputValidationError`，API 返回 HTTP 500 和 `execution_failed`，并保留失败日志但不返回伪造结果。

## 8. 审计与结论生成

### 8.1 审计事件

每个操作生成一个 `AuditEvent`。`step_id` 使用 `step-001`、`step-002` 的顺序格式。每个事件必须记录：

- 输入工作表和输出工作表。
- 使用的字段。
- 输入行数和输出行数。
- 最多 200 个受影响源行号。
- 过滤条件、分组字段、聚合函数、比较 key 或公式表达式。

`_audit` 工作表使用以下列：`step_id`、`operation`、`input_sheets`、`output_sheets`、`columns`、`input_rows`、`output_rows`、`affected_rows`、`details_json`。

### 8.2 结论生成规则

数值型结论必须由执行结果生成。第一版至少生成：

- 处理前后行数。
- 发现的问题数量。
- 去重删除行数。
- 汇总结果中最大值和最小值。
- 对比结果中新增、删除、变化数量。

每个 `Conclusion` 必须引用一个真实存在的 `step_id`。若无法找到来源，不生成该结论。结论文本可以由模型润色，但模型只能接收真实指标和来源，不能自行补充数值。

## 9. Planner 设计

### 9.1 统一接口

```python
class Planner(Protocol):
    def plan(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        ...
```

Planner 返回的所有 `source_sheets`、操作中的 `sheet`、`left_sheet` 和 `right_sheet` 都必须是 `SheetRef.ref` 完整引用。单文件也使用完整引用；前端可以在展示层把 `file_id::明细` 显示成文件名和“明细”两段，但不能把裸名称传回执行接口。

### 9.2 DemoPlanner

DemoPlanner 不调用网络，使用规则识别有限但完整的通用任务。它必须支持：

- “检查数据问题、统一金额格式并按部门汇总”。
- “去重并生成问题清单”。
- “筛选状态为某值的记录”。
- “补充空白公式”。
- “比较两个工作表的变化”。

字段匹配顺序：先精确匹配规范化后的列名，再匹配别名：

| 语义 | 别名示例 |
|---|---|
| 金额 | 金额、金额合计、费用、销售额、收入 |
| 部门 | 部门、所属部门、组织、单位 |
| 日期 | 日期、时间、发生日期、创建时间 |
| 编号 | 编号、ID、编码、订单号、员工编号 |
| 状态 | 状态、进度、处理状态 |

找不到任务所需字段时，抛出 `AmbiguousRequestError`，返回 `ambiguous_request`，并携带一个澄清问题。DemoPlanner 不能根据预览中的数据值臆造缺失字段。

### 9.3 CompatiblePlanner

CompatiblePlanner 使用 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`。请求只包含：

- 用户自然语言请求。
- `WorkbookInspection` 的元数据和最多 20 行预览。
- 操作白名单及字段说明。
- 要求返回 `OperationPlan` JSON 的 JSON Schema。

模型系统提示必须表达以下规则：

```text
只输出符合 OperationPlan schema 的 JSON。
只能使用给定的工作表和列。
不要输出 Python、Shell、SQL 或文件路径。
不要输出任何计算后的指标数值。
不确定匹配字段时返回 clarification_question，不要猜测。
```

模型响应解析失败、JSON Schema 校验失败或模型超时时，返回 `model_invalid_response` 或 `model_timeout`。不得把原始模型响应完整返回给前端。

## 10. Service 层接口

```python
def analyze_files(paths: list[Path]) -> list[WorkbookInspection]:
    ...


def create_plan(
    paths: list[Path],
    request: str,
) -> OperationPlan:
    ...


def run_plan(
    paths: list[Path],
    plan: OperationPlan,
    confirmation_token: str | None,
) -> ExecutionResult:
    ...
```

Service 层必须：

1. 先检查所有文件存在且扩展名受支持。
2. 先解析所有文件，再调用 Planner。
3. 对跨文件工作表使用内部唯一引用，避免同名工作表冲突；对外显示仍保留文件名和工作表名。
4. 对模型返回的计划重新执行字段、操作和确认校验。
5. 执行失败时保留源文件和审计错误，不生成成功结果。

## 11. API 合同

所有 API 路径以 `/api` 开头。成功响应使用 JSON；下载接口返回二进制文件。

### 11.1 健康检查

```http
GET /api/health
```

响应 `200`：

```json
{
  "status": "ok",
  "mode": "demo"
}
```

### 11.2 上传文件

```http
POST /api/files
Content-Type: multipart/form-data
```

字段名固定为 `file`。成功响应 `201`：

```json
{
  "file_id": "uuid",
  "filename": "sample.xlsx",
  "size_bytes": 12345,
  "inspection": {
    "filename": "sample.xlsx",
    "file_type": "xlsx",
    "sheets": []
  }
}
```

### 11.3 生成计划

```http
POST /api/plans
Content-Type: application/json
```

请求：

```json
{
  "file_ids": ["uuid-1", "uuid-2"],
  "request": "检查数据问题并按部门汇总金额"
}
```

成功响应 `200`：

```json
{
  "plan": {
    "id": "plan-uuid",
    "source_sheets": ["uuid-1::明细"],
    "operations": [],
    "outputs": ["清洗后数据", "汇总结果", "问题清单"],
    "explanation": "...",
    "clarification_question": null,
    "requires_confirmation": true
  }
}
```

### 11.4 执行计划

```http
POST /api/executions
Content-Type: application/json
```

请求：

```json
{
  "file_ids": ["uuid-1"],
  "plan": {},
  "confirmation_token": "confirm:plan-uuid"
}
```

成功响应 `201`：

```json
{
  "output_id": "uuid",
  "sheets": ["原始_uuid-1_明细", "清洗后数据", "汇总结果", "问题清单", "_audit"],
  "metrics": {},
  "conclusions": [],
  "audit_events": []
}
```

### 11.5 下载结果

```http
GET /api/outputs/{output_id}
```

返回 `200`，`Content-Type` 必须以 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` 开头，使用 `Content-Disposition: attachment`。

### 11.6 获取审计

```http
GET /api/outputs/{output_id}/audit
```

返回：

```json
{
  "output_id": "uuid",
  "events": [],
  "conclusions": []
}
```

### 11.7 错误响应

错误响应固定为：

```json
{
  "error_code": "confirmation_required",
  "message": "该操作预计会删除 8 行数据，请确认后继续。",
  "details": {}
}
```

错误码与状态码：

| HTTP | `error_code` | 使用场景 |
|---:|---|---|
| 400 | `unsupported_file` | 扩展名不支持 |
| 400 | `invalid_request` | 请求体字段错误 |
| 400 | `invalid_plan` | DSL 校验失败 |
| 400 | `ambiguous_request` | 字段或匹配键无法确定 |
| 404 | `file_not_found` | file_id 不存在 |
| 404 | `output_not_found` | output_id 不存在 |
| 409 | `confirmation_required` | 缺失或错误确认令牌 |
| 413 | `file_too_large` | 超过 25 MiB |
| 502 | `model_timeout` | 模型请求超时 |
| 502 | `model_invalid_response` | 模型返回无法解析 |
| 503 | `model_not_configured` | LLM 模式缺少配置 |
| 500 | `execution_failed` | 执行或输出校验失败 |

## 12. SQLite 元数据设计

第一版使用 `sqlite3` 初始化以下表：

```sql
CREATE TABLE files (
  id TEXT PRIMARY KEY,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL UNIQUE,
  file_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  inspection_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE outputs (
  id TEXT PRIMARY KEY,
  stored_path TEXT NOT NULL UNIQUE,
  source_file_ids_json TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

`stored_path` 必须是应用数据目录下的绝对路径或经过校验的相对路径。任何下载请求必须先按 ID 查询数据库，再校验解析后的路径位于 `runtime/outputs` 目录内。

## 13. 前端设计

### 13.1 页面结构

页面只有工作台，不做营销首页。桌面端为三栏布局：

```text
左栏：文件与工作表
中栏：任务输入、计划和确认
右栏：体检、结果、结论和来源
```

900px 以下改为纵向堆叠，文件列表、任务区、结果区仍保留完整功能。

### 13.2 前端状态

`App` 至少维护：

```ts
type WorkflowStatus =
  | "idle"
  | "uploading"
  | "inspected"
  | "planning"
  | "plan_ready"
  | "executing"
  | "completed"
  | "error";
```

状态转换：

```text
idle -> uploading -> inspected -> planning -> plan_ready
plan_ready -> executing -> completed
任意请求状态 -> error
```

### 13.3 前端 API 函数

```ts
export function uploadFile(file: File): Promise<FileUploadResponse>;
export function createPlan(fileIds: string[], request: string): Promise<PlanResponse>;
export function executePlan(input: ExecuteRequest): Promise<ExecutionResponse>;
export function downloadOutput(outputId: string): Promise<void>;
export function getAudit(outputId: string): Promise<AuditView>;
```

所有 API 错误统一解析 `error_code` 和 `message`，前端显示 `message`，调试信息只写浏览器控制台，不把服务器路径显示给用户。

### 13.4 交互规则

- 文件选择器只接受 `.xlsx,.xls,.csv`。
- 没有文件时，任务输入和计划执行按钮禁用。
- 没有计划时，执行按钮禁用。
- `requires_confirmation=true` 时，第一次点击执行显示影响范围，第二次点击才调用执行接口。
- 结果页面显示下载按钮、结论卡片、指标变化和可展开来源。
- 上传、规划和执行期间显示加载状态，避免重复提交。
- 失败后保留已上传文件和原有体检结果，允许用户修改任务重新规划。

### 13.5 前端防腐层

前端不得在 React 组件中直接使用后端 DTO、`fetch`、HTTP 状态码或后端错误码。前端分为三层：

```text
components/hooks
      |
frontend domain models + use-case functions
      |
API anti-corruption layer
      |
HTTP transport + backend JSON
```

目录固定为：

```text
frontend/src/
  api/
    httpClient.ts       # 唯一的 HTTP 入口、拦截器和 ApiError
    contracts.ts        # 后端传输 DTO 的 Zod schema 和推导类型
    fileApi.ts          # 上传用例
    planApi.ts          # 规划用例
    executionApi.ts     # 执行、下载和审计用例
    mappers.ts          # DTO -> 前端领域模型
  domain/
    models.ts           # 前端显示模型，不复用后端字段类型
    workflow.ts         # 工作流状态和 reducer
  hooks/
    useWorkflow.ts
    useUpload.ts
    usePlan.ts
    useExecution.ts
  components/
    primitives/
    feedback/
    layout/
    FilePanel.tsx
    TaskPanel.tsx
    InspectionPanel.tsx
    PlanPanel.tsx
    ResultPanel.tsx
```

防腐层规则：

1. 只有 `api/` 可以知道 `/api/...` 路径、HTTP 方法、后端 JSON 字段名、`error_code` 和状态码。
2. `contracts.ts` 使用 Zod 校验运行时响应；TypeScript 类型必须从 schema 推导，不能只依赖编译期接口。
3. `mappers.ts` 将后端 DTO 转为前端模型，例如 `SheetInspectionDto` 转为 `SheetSummary`，组件只能消费 `SheetSummary`。
4. 后端字段重命名、错误码变化或空值变化只允许在 `api/` 内适配，不能扩散到组件。
5. 组件不能接收 `Response`、`AxiosResponse`、`unknown` 或后端 DTO；组件 props 必须是前端领域模型或明确的 UI props。
6. 下载必须通过 `executionApi.downloadOutput(outputId)`，由防腐层处理二进制响应、文件名和错误；组件不能拼接任意下载路径。

### 13.6 API 客户端和统一拦截器

第一版使用浏览器原生 `fetch`，不引入 Axios。所有网络请求必须经过 `httpClient.request`，禁止在组件、hook 或其他 API 文件中直接调用 `fetch`。

```ts
export type RequestContext = {
  requestId: string
  signal?: AbortSignal
  timeoutMs?: number
}

export class ApiError extends Error {
  readonly status: number
  readonly errorCode: string
  readonly details: unknown
  readonly requestId: string
}

export interface HttpClient {
  request<T>(
    path: string,
    init?: RequestInit,
    context?: Partial<RequestContext>,
  ): Promise<T>
}
```

`httpClient` 必须按以下顺序执行：

1. 拼接固定 `VITE_API_BASE_URL` 和相对 API 路径；路径必须以 `/api/` 开头。
2. 生成 `crypto.randomUUID()` 请求 ID，并通过 `X-Request-ID` 发送。
3. 对没有外部 `signal` 的请求创建 `AbortController`，默认超时 30 秒；上传和执行默认 120 秒。
4. 统一设置 `Accept: application/json`；JSON 请求设置 `Content-Type: application/json`，`FormData` 请求不手动设置 multipart boundary。
5. 响应状态为 2xx 时按调用方声明解析 JSON 或 Blob。
6. 非 2xx 时解析 `{ error_code, message, details }`，创建 `ApiError`；无法解析时使用稳定的 `network_error` 或 `http_error`。
7. `AbortError` 转换成 `request_timeout`，并保留可展示的中文提示。
8. 记录请求 ID、路径、耗时和结果码；生产日志不得记录文件内容、请求体、API Key 或完整模型响应。

拦截器分为四个纯函数，避免隐藏副作用：

```ts
type RequestInterceptor = (
  input: RequestInput,
) => RequestInput | Promise<RequestInput>

type ResponseInterceptor = (
  response: Response,
  context: RequestContext,
) => Response | Promise<Response>

type ErrorInterceptor = (
  error: unknown,
  context: RequestContext,
) => never | Promise<never>
```

默认拦截器固定为：请求 ID、超时、响应错误标准化、网络错误标准化和调试计时。第一版不自动重试上传、执行和下载请求；POST/写操作重试可能造成重复任务。健康检查和审计 GET 也不自动重试，除非后续明确加入幂等键。

### 13.7 传输契约与领域模型

`frontend/src/api/contracts.ts` 必须定义以下 schema：`fileUploadResponseSchema`、`planResponseSchema`、`executionResponseSchema`、`auditResponseSchema` 和 `errorResponseSchema`。关键后端 DTO 字段必须在运行时校验：

```ts
const fileUploadResponseSchema = z.object({
  file_id: z.string().uuid(),
  filename: z.string().min(1),
  size_bytes: z.number().int().nonnegative(),
  inspection: workbookInspectionDtoSchema,
})
```

前端领域模型使用前端命名和展示需要的结构，例如：

```ts
type FileItem = {
  id: string
  name: string
  sizeBytes: number
  sheets: SheetSummary[]
}

type SheetSummary = {
  ref: string
  displayName: string
  rowCount: number
  columnCount: number
  issues: IssueSummary[]
}

type PlanView = {
  id: string
  explanation: string
  steps: PlanStepView[]
  outputNames: string[]
  requiresConfirmation: boolean
}
```

`mappers.ts` 必须处理：snake_case 到 camelCase、可选字段默认值、来源字段展示名、文件引用显示名和错误码到用户提示的映射。组件不得直接写 `response.json().plan.operations` 之类的后端结构访问。

### 13.8 通用组件和组件边界

通用组件只负责展示和用户交互，通过 props 接收数据和回调；它们不能调用 API、读取 Context 中的后端数据或包含业务字段映射。

必须抽离以下组件：

```text
components/primitives/
  Button.tsx       # variant、size、loading、disabled、icon
  IconButton.tsx   # 必须提供 aria-label 和 title
  Badge.tsx
  Card.tsx
  Divider.tsx
  Input.tsx
  TextArea.tsx
  Progress.tsx
  Table.tsx
  EmptyState.tsx
  Skeleton.tsx

components/feedback/
  Alert.tsx
  ToastRegion.tsx
  ErrorState.tsx
  ConfirmDialog.tsx

components/layout/
  AppShell.tsx
  Panel.tsx
  PanelHeader.tsx
  SectionHeader.tsx
```

复合组件使用组合而非继承：`Panel` 负责边界和间距，`PanelHeader` 负责标题和操作区，`Table` 负责表头、空状态和滚动容器；领域组件负责把 `FileItem`、`PlanView` 和 `ExecutionView` 映射为这些通用组件的 props。

组件边界固定为：

- `FilePanel`：只处理文件选择、上传回调和文件列表展示。
- `InspectionPanel`：只展示 `SheetSummary` 和 `IssueSummary`。
- `TaskPanel`：只编辑用户请求并触发 `onCreatePlan`。
- `PlanPanel`：只展示 `PlanView`，触发 `onConfirm`。
- `ResultPanel`：只展示 `ExecutionView`，触发 `onDownload` 和来源展开。
- `App`/`useWorkflow`：唯一负责跨面板工作流编排。

### 13.9 状态管理和 hook 规则

第一版使用 `WorkflowProvider + useReducer`，不引入 Redux 或 Zustand。Reducer 只处理可序列化的领域状态；文件对象和 AbortController 保存在 hook 的局部引用中，不放进 reducer。

状态至少包含：

```ts
type WorkflowState = {
  status: WorkflowStatus
  files: FileItem[]
  selectedFileIds: string[]
  activeSheetRef: string | null
  requestText: string
  plan: PlanView | null
  result: ExecutionView | null
  error: UserFacingError | null
}
```

hook 规则：

- `useUpload` 只调用 `fileApi.uploadFile`，成功后 dispatch `FILE_ADDED`。
- `usePlan` 只调用 `planApi.createPlan`，处理规划中的 loading 和错误。
- `useExecution` 只调用 `executionApi.executePlan` 和 `downloadOutput`。
- hook 不返回后端 DTO，不在 hook 中渲染 JSX。
- 所有异步操作在卸载时取消；过期响应不能覆盖较新的 workflow 状态。
- 任务输入最多 2,000 个字符；空白输入不提交。

### 13.10 统一样式和设计令牌

样式只使用 `frontend/src/styles.css` 及其拆分文件中的 CSS variables 和 class，业务组件不写大段 inline style。颜色、间距、字号、圆角、阴影、边框和层级必须来自令牌：

```css
:root {
  --color-bg: #f4f6f8;
  --color-surface: #ffffff;
  --color-text: #17212b;
  --color-muted: #66727f;
  --color-border: #d9e0e7;
  --color-accent: #1769aa;
  --color-success: #1f7a4d;
  --color-warning: #a86400;
  --color-danger: #b42318;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --shadow-panel: 0 1px 3px rgb(23 33 43 / 8%);
}
```

样式规则：

- 使用 `data-state`、`data-variant` 和语义 class 表达状态，不拼接任意用户输入生成 class 名。
- 组件的布局尺寸由 CSS grid/flex 和最小尺寸控制，按钮、工具栏、面板标题不能因文本变化导致跳动。
- 所有交互控件有 `:focus-visible` 样式；图标按钮必须有 `aria-label` 和 tooltip。
- 颜色不能只依赖色彩表达错误，错误同时显示图标或文本。
- 表格预览横向滚动，长字段截断但可通过 title 或详情展开查看。
- 900px 以下切换单列；不以视口宽度缩放字号。
- 页面、面板、卡片不层层嵌套成装饰性卡片；面板用于工作区分区，卡片只用于重复结果项和结论。

### 13.11 前端错误与异常边界

应用根部必须使用 `ErrorBoundary` 捕获渲染异常，显示可恢复的错误页并提供“重新加载工作区”操作。网络错误由 `ApiError` 统一转换为 `UserFacingError`，映射如下：

| `error_code` | 用户提示 |
|---|---|
| `unsupported_file` | 暂不支持该文件格式，请上传 xlsx、xls 或 csv。 |
| `file_too_large` | 文件超过 25 MiB，请缩小文件后重试。 |
| `ambiguous_request` | 任务中的字段或匹配方式不明确，请补充说明。 |
| `confirmation_required` | 该操作会修改或删除数据，请确认影响范围后继续。 |
| `execution_failed` | 文件处理失败，源文件未被修改，请调整任务后重试。 |
| `model_timeout` | 智能规划暂时超时，请重试或切换演示模式。 |
| 其他 | 服务暂时不可用，请稍后重试。 |

错误提示不显示服务器绝对路径、堆栈、原始模型输出或请求体。表单验证错误就地显示；网络错误显示在 `ToastRegion`，计划和执行错误同时保留在对应面板。

## 14. 安全与资源限制

- 上传大小限制 25 MiB。
- 只根据扩展名白名单和文件头进行文件类型校验。
- 使用 UUID 生成存储文件名，原始文件名只用于展示。
- 使用 `Path.resolve()` 校验所有读写路径位于配置的数据目录下。
- 上传文件不可执行，不加载宏和嵌入脚本。
- 不执行模型返回的代码、命令、路径或 SQL。
- 导出文本单元格若以 `=`, `+`, `-`, `@` 开头，按 Excel 公式注入策略转义为文本，除非该单元格是由 `fill_formula` 明确生成的公式。
- API Key 只从后端环境变量读取，不进入 API 响应、日志或前端 bundle。
- 错误日志记录错误码和任务 ID，不记录完整文件内容。
- 生产环境必须启用 HTTPS、自动重启、日志轮转和过期文件清理。

## 15. 测试设计与完成标准

### 15.1 单元测试

解析器必须覆盖：

- `.xlsx` 多工作表。
- `.xls` 读取。
- CSV UTF-8 和 GB18030。
- 空工作表。
- 前置说明行和空表头。
- 重复行、空值、混合数字、混合日期。
- 不支持扩展名和不存在文件。

操作与执行器必须覆盖：

- 未知操作被拒绝。
- 缺失工作表或列被拒绝。
- `normalize` 的数字、日期和文本转换。
- `deduplicate` 的 first/last 和确认令牌。
- filter 的 all/any 及 null 条件。
- group summary 的 sum/mean/count/min/max。
- compare 的 added/removed/changed。
- formula fill 只填空白、范围校验和公式数量。
- 问题清单和隐藏 `_audit` 工作表。
- 输出可重新打开，源文件 SHA-256 不变。

### 15.2 API 测试

必须覆盖完整链路：

```text
upload -> inspect -> create plan -> missing confirmation -> execute -> download -> audit
```

并覆盖每个规定错误码至少一次。测试使用临时数据目录，不能污染项目根目录的 `runtime`。

### 15.3 前端测试

必须验证：

- 上传成功后显示文件和工作表。
- 体检问题可见。
- 提交任务后显示计划。
- 高影响计划显示确认提示。
- 确认时发送 `confirm:<plan.id>`。
- 完成后显示结论和真实下载 URL。
- API 错误显示用户可理解的错误信息。

### 15.4 端到端验收

使用 `fixtures/expenses_and_budget.xlsx` 完成以下请求：

> 检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。

必须得到：

1. 上传后显示工作表、字段、行数和问题。
2. 计划包含 `normalize`、`deduplicate`、`group_summary`、`create_issue_sheet`。
3. 计划标记 `requires_confirmation=true`。
4. 未确认时返回 `confirmation_required`。
5. 确认后生成新的 `.xlsx`。
6. 输出包含清洗数据、汇总结果、问题清单和隐藏 `_audit`。
7. 至少一个结论引用真实审计 `step_id`。
8. 原始文件仍存在且 SHA-256 不变。

### 15.5 完成命令

```powershell
python -m pytest -q
npm run test --prefix frontend -- --run
npm run build --prefix frontend
python scripts/create_fixtures.py
```

所有命令成功、端到端验收通过、前后端开发服务可以启动，才可以将第一版标记为完成。

## 16. 实现顺序

编码 Agent 必须按以下顺序提交：

1. 项目骨架、配置、健康检查和依赖。
2. Pydantic 领域模型和文件解析器。
3. 操作 DSL、确认策略、确定性执行器和审计。
4. DemoPlanner、CompatiblePlanner 和 Service。
5. FastAPI 文件、计划、执行、下载和审计接口。
6. React 三栏工作台和前端测试。
7. 三组模拟 Excel、端到端测试和 README。
8. 本地启动、双次完整演示和最终质量检查。

每一步都必须产生可运行的中间状态，并在提交信息中说明对应模块。第一版完成后，再另行设计 Word/PDF 解析、规则引用和异步任务，不在本实现中扩大范围。
