# 表析 Agent

面向普通办公人员的 Excel/CSV 工作流智能体。上传文件后用自然语言描述任务，智能体会先生成可检查、可批准的工作流图，再由后端执行清洗、汇总、对比、合并和导出，最后提供可下载的 Excel 结果。

第一版支持 `.xlsx`、`.xls`、`.csv`；不支持 Word/PDF/扫描件。

## 功能

- 支持 `.xlsx`、`.xls`、`.csv` 文件上传和工作表结构预览。
- 通过工作流图表达上传、检查、清洗、去重、筛选、汇总、合并、对比和导出。
- 支持多文件、多工作表、分支和汇合节点。
- 执行前需要用户批准；执行过程显示节点状态、耗时、缓存和错误。
- 导出节点生成可下载的 `.xlsx` 文件，并保留审计工作表。
- 文本列 `count` 按非空、非空白值计数；工作表选择按节点输入严格绑定。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn backend.app.main:app --reload --port 8000
```

```bash
npm install --prefix frontend
npm run dev --prefix frontend
```

浏览器访问 `http://localhost:5173`，后端 API 在 `http://localhost:8000`。

也可以在项目根目录运行：

```powershell
npm run dev
```

它会同时启动后端和前端。

## 模式

- `APP_MODE=demo`（默认）：使用内置规则规划器，无需模型 Key。
- `APP_MODE=llm`：使用 `MODEL_BASE_URL`、`MODEL_API_KEY` 和 `MODEL_NAME` 配置的 Anthropic Messages 兼容接口。

模型模式至少需要：

```dotenv
APP_MODE=llm
MODEL_BASE_URL=https://your-provider.example
MODEL_API_KEY=your-api-key
MODEL_NAME=your-model-name
```

## 推荐演示任务

上传 `fixtures/expenses_and_budget.xlsx`，输入：

> 检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。

操作流程：

1. 上传一个或多个表格文件。
2. 输入自然语言任务，例如“按部门汇总支出并与预算表合并”。
3. 检查画布中的节点、连线、参数和输入输出表。
4. 点击“执行”，等待节点完成。
5. 选中导出节点，在右侧详情中点击文件链接下载 Excel。

导出结果包含处理后的工作表和 `_audit` 审计工作表；源文件不会被原地修改。

## 测试

```powershell
python -m pytest -q
npm run test --prefix frontend -- --run
npm run build --prefix frontend
```

## 目录结构

```text
backend/
  app/
    main.py
    config.py
    schemas.py
    api/routes.py
    domain/       # 表格解析、转换和领域逻辑
    mcp/          # 工作流图、节点 handler 和执行引擎
    api/          # FastAPI 路由与 SSE
    llm/          # 模型适配层
  tests/
frontend/
  src/
fixtures/
```

## 不支持的内容

- Word / PDF / 扫描件
- Excel 宏 / 嵌入脚本
- 用户账号、权限、计费
- 大文件异步任务队列
- 模型任意代码执行

当前定位是本地开发和中小型文件处理。执行状态、节点 artifact 和审计信息已经持久化，后续可接入异步任务队列。
