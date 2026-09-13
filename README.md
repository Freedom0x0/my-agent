# 表析 Agent

面向普通办公人员的 Excel/CSV 通用分析智能体。上传一个或多个 Excel 文件，用自然语言描述需要完成的工作；系统先理解表格并展示可确认的执行计划，再完成清洗、分析、对比或改表，最后交付可下载的新 Excel 和可追溯的分析结果。

第一版支持 `.xlsx`、`.xls`、`.csv`；不支持 Word/PDF/扫描件。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python scripts/create_fixtures.py
uvicorn backend.app.main:app --reload --port 8000
```

```bash
npm install --prefix frontend
npm run dev --prefix frontend
```

浏览器访问 `http://localhost:5173`，后端 API 在 `http://localhost:8000`。

## 模式

- `APP_MODE=demo` （默认）：使用内置规则规划器，无需任何模型 Key。
- `APP_MODE=llm`：使用 `MODEL_BASE_URL` / `MODEL_API_KEY` / `MODEL_NAME` 配置的 OpenAI 兼容接口。

## 推荐演示任务

上传 `fixtures/expenses_and_budget.xlsx`，输入：

> 检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。

执行完成后：
1. 下载新生成的 `.xlsx`，包含原始数据快照、清洗后数据、汇总结果、问题清单和隐藏 `_audit` 工作表。
2. 源文件 SHA-256 不变。
3. 结论卡片中的每条结论都引用真实审计 `step_id`。

## 测试

```powershell
python -m pytest -q
npm run test --prefix frontend -- --run
npm run build --prefix frontend
python scripts/create_fixtures.py
```

## 目录结构

```text
backend/
  app/
    main.py
    config.py
    schemas.py
    api/routes.py
    domain/
      parser.py
      operations.py
      executor.py
      audit.py
      service.py
    llm/
      base.py
      demo.py
      compatible.py
  tests/
frontend/
  src/
fixtures/
scripts/create_fixtures.py
```

## 不支持的内容

- Word / PDF / 扫描件
- Excel 宏 / 嵌入脚本
- 用户账号、权限、计费
- 大文件异步任务队列
- 模型任意代码执行

第一版采用同步执行中小型文件，状态字段已保留以便未来接入任务队列。