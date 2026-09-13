# 演示数据

本目录提供三份故意引入问题的 Excel 工作簿，用于演示和测试：

- `personnel_messy.xlsx` — 人员信息台账，含重复行、格式不统一的联系方式和证件号、缺失字段。
- `project_progress_messy.xlsx` — 项目进度表，含不同格式的日期（`YYYY-MM-DD` / `YYYY/MM/DD` / `YYYY.MM.DD` / `YYYY年M月D日`）、不规范的状态值。
- `expenses_and_budget.xlsx` — 月度收支明细与预算，含千分位金额、中文单位金额、跨表预算对比。

## 生成

```bash
python scripts/create_fixtures.py
```

脚本会覆盖同名文件。所有数据均为虚构，使用中文姓名和合成编号，不包含真实个人信息。