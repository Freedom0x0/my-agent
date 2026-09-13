# 现场演示脚本

## 5 分钟主流程（expenses_and_budget.xlsx）

1. 打开工作台 `http://localhost:5173`。
2. 上传 `fixtures/expenses_and_budget.xlsx`。
3. 等待右侧体检结果：行数、列类型、`duplicate_rows`、`mixed_date`、`mixed_numeric` 问题。
4. 输入任务：

   > 检查数据问题，统一格式并去重；按部门汇总；把处理结果和问题清单生成到一个新的 Excel。

5. 点击「生成执行计划」，确认计划包含 `normalize`、`deduplicate`、`group_summary`、`create_issue_sheet`，`requires_confirmation=true`。
6. 点击「执行计划」，第二次点击确认高影响操作。
7. 在右侧结果区查看结论卡片、指标、来源 `step_id`。
8. 点击「下载处理后的 Excel」，在 Excel 中打开：包含原始数据快照、清洗后数据、汇总结果、问题清单和隐藏 `_audit` 工作表。
9. 验证源文件 SHA-256 与执行前一致（见 `runtime/outputs/<output_id>.xlsx`）。

## 通用路径 1：人员台账去重

上传 `fixtures/personnel_messy.xlsx`，输入：

> 按证件号去重并生成问题清单

执行，确认计划 `kinds=[deduplicate, create_issue_sheet]`，输出包含清洗后数据和问题清单。

## 通用路径 2：项目筛选

上传 `fixtures/project_progress_messy.xlsx`，输入：

> 筛选状态为进行中的项目

执行，确认计划 `kinds=[filter]`，输出包含筛选结果。

## 命令行验证

```powershell
# 启动后端（demo 模式无需 Key）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python scripts/create_fixtures.py
uvicorn backend.app.main:app --port 8000

# 另开终端跑端到端脚本
python scripts/live_demo.py
python scripts/live_generalization.py
```