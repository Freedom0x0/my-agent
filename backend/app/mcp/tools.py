"""Anthropic tool definitions for the 11 tablex_* tools."""
from __future__ import annotations

# Schema follows Anthropic's tool format: name + description + input_schema (JSON Schema).

TABLEX_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "tablex_upload",
        "description": "加载已上传的文件到会话中，并检测其数据质量问题。需要 file_id（前端通过 /api/files 上传后获得）。调用此工具后，文件中的所有工作表会被加载，后续工具即可引用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "已上传文件的 ID",
                },
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "tablex_inspect",
        "description": "分析指定文件（或其中某个工作表）的数据质量问题：列类型推断、空值、重复行、混合类型等。仅做检查，不修改数据。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "文件 ID"},
                "sheet": {
                    "type": "string",
                    "description": "可选：具体工作表名。若省略，分析第一个工作表",
                },
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "tablex_normalize",
        "description": "统一指定列的格式（数字/日期/文本）。会原地修改对应工作表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string", "description": "工作表名"},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要统一格式的列名列表",
                    "minItems": 1,
                },
                "target_type": {
                    "type": "string",
                    "enum": ["number", "date", "text"],
                    "description": "目标类型",
                },
            },
            "required": ["file_id", "sheet", "columns", "target_type"],
        },
    },
    {
        "name": "tablex_deduplicate",
        "description": "按指定列删除重复行。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "key_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "keep": {
                    "type": "string",
                    "enum": ["first", "last"],
                    "description": "保留哪一条，默认为 first",
                },
            },
            "required": ["file_id", "sheet", "key_columns"],
        },
    },
    {
        "name": "tablex_filter",
        "description": "按条件筛选行，匹配的行写入新工作表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "conditions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "operator": {
                                "type": "string",
                                "enum": ["eq", "ne", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null", "in"],
                            },
                            "value": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "number"},
                                    {"type": "boolean"},
                                    {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "number"}]}},
                                    {"type": "null"},
                                ],
                            },
                        },
                        "required": ["column", "operator"],
                    },
                },
                "match": {"type": "string", "enum": ["all", "any"], "description": "条件组合方式，默认 all"},
                "output_sheet": {"type": "string", "description": "输出工作表名，默认 '筛选结果'"},
            },
            "required": ["file_id", "sheet", "conditions"],
        },
    },
    {
        "name": "tablex_group_summary",
        "description": "按列分组并对数值列做聚合（sum/mean/count/min/max），结果写入新工作表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "metrics": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["sum", "mean", "count", "min", "max"],
                        },
                    },
                    "description": "形如 {\"金额\": [\"sum\", \"mean\"]}",
                },
                "output_sheet": {"type": "string", "description": "默认 '汇总结果'"},
            },
            "required": ["file_id", "sheet", "group_by", "metrics"],
        },
    },
    {
        "name": "tablex_compare",
        "description": "对比两个工作表的差异（按 key_columns 匹配），结果写入新工作表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "left_ref": {"type": "string", "description": "左表 SheetRef: file_id::sheet_name"},
                "right_ref": {"type": "string", "description": "右表 SheetRef: file_id::sheet_name"},
                "key_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "output_sheet": {"type": "string", "description": "默认 '对比结果'"},
            },
            "required": ["left_ref", "right_ref", "key_columns"],
        },
    },
    {
        "name": "tablex_fill_formula",
        "description": "为目标列空白单元格补公式。公式支持 {列名} 和 {行号} 占位符，仅允许白名单函数（ROUND/SUM/IF）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "target_column": {"type": "string"},
                "expression": {
                    "type": "string",
                    "description": "公式表达式，例如 {金额}*ROUND({数量},2)",
                },
                "start_row": {"type": "integer", "minimum": 2},
                "end_row": {"type": "integer", "minimum": 2},
                "only_blank": {
                    "type": "boolean",
                    "description": "仅填充空白单元格，默认 true",
                },
            },
            "required": ["file_id", "sheet", "target_column", "expression", "start_row", "end_row"],
        },
    },
    {
        "name": "tablex_sort",
        "description": "按指定列对工作表排序（原地修改）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "排序方向，默认 asc",
                },
            },
            "required": ["file_id", "sheet", "column"],
        },
    },
    {
        "name": "tablex_fill_null",
        "description": "填充空值。method: mean（数值均值）/ ffill（向前填充）/ bfill（向后填充）/ value（用 value 字段填充）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["mean", "ffill", "bfill", "value"],
                },
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "null"},
                    ],
                    "description": "当 method='value' 时使用",
                },
            },
            "required": ["file_id", "sheet", "column", "method"],
        },
    },
    {
        "name": "tablex_export",
        "description": "将当前 session 中所有处理后的工作表写入一个新的 xlsx 文件，返回 output_name 和 sheets 列表供前端预览。",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "结果文件的人类可读名字（必填，会作为右侧预览器 tab 标题）",
                },
            },
            "required": ["output_name"],
        },
    },
    {
        "name": "tablex_join",
        "description": "按公共列合并两个工作表（可跨文件 / 跨 sheet）。支持 inner/left/right/full 四种连接方式；on 或 left_on+right_on 二选一；重名加后缀。",
        "input_schema": {
            "type": "object",
            "properties": {
                "left": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "sheet": {"type": "string"},
                    },
                    "required": ["file_id", "sheet"],
                },
                "right": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "sheet": {"type": "string"},
                    },
                    "required": ["file_id", "sheet"],
                },
                "on": {"type": "string", "description": "公共列名（左右表同名时用）"},
                "left_on": {"type": "string"},
                "right_on": {"type": "string"},
                "how": {
                    "type": "string",
                    "enum": ["inner", "left", "right", "full"],
                    "default": "inner",
                },
                "suffix": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["_l", "_r"],
                    "description": "重名列后缀，长度 2",
                },
            },
            "required": ["left", "right"],
        },
    },
    {
        "name": "tablex_pivot",
        "description": "对工作表做透视 / 反透视 / 交叉表。operation=pivot 时需 index+columns+values，operation=unpivot 时需 index，operation=crosstab 时需 index+columns。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "operation": {
                    "type": "string",
                    "enum": ["pivot", "unpivot", "crosstab"],
                },
                "index": {"type": "array", "items": {"type": "string"}},
                "columns": {"type": "array", "items": {"type": "string"}},
                "values": {"type": "array", "items": {"type": "string"}},
                "aggfunc": {
                    "type": "string",
                    "enum": ["sum", "mean", "count", "min", "max"],
                    "default": "sum",
                },
                "fill_value": {"type": "number", "default": 0},
                "var_name": {"type": "string", "default": "variable"},
                "value_name": {"type": "string", "default": "value"},
            },
            "required": ["file_id", "sheet", "operation"],
        },
    },
    {
        "name": "tablex_validate",
        "description": "按规则校验工作表。rule.type 支持 primary_key / foreign_key / range / format / enum / not_null。fail_strategy 决定 report_only(返回报告) / mark(原 sheet 加 _validation_<col>_<type> 列) / filter(只保留通过行)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "primary_key", "foreign_key", "range",
                                    "format", "enum", "not_null",
                                ],
                            },
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                            "pattern": {"type": "string"},
                            "values": {"type": "array"},
                            "ref": {
                                "type": "object",
                                "description": "foreign_key 引用；本工具已简化为 values 字段直接提供候选集合",
                            },
                        },
                        "required": ["column", "type"],
                    },
                    "minItems": 1,
                },
                "fail_strategy": {
                    "type": "string",
                    "enum": ["mark", "filter", "report_only"],
                    "default": "report_only",
                },
            },
            "required": ["file_id", "sheet", "rules"],
        },
    },
    {
        "name": "tablex_chart",
        "description": "根据工作表数据生成图表。chart_type=auto 时根据 x 列类型和 y 数量自动选择（饼/折/柱）。结果图 PNG 嵌入到新输出 xlsx 的 '图表' sheet。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "chart_type": {
                    "type": "string",
                    "enum": ["auto", "bar", "line", "pie", "scatter", "heatmap"],
                    "default": "auto",
                },
                "x": {"type": "string"},
                "y": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "title": {"type": "string"},
                "style": {
                    "type": "object",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "enum": ["light", "dark"],
                            "default": "light",
                        },
                        "width": {"type": "integer", "default": 800},
                        "height": {"type": "integer", "default": 500},
                    },
                },
            },
            "required": ["file_id", "sheet", "x", "y"],
        },
    },
    {
        "name": "tablex_read_chunk",
        "description": "分块读取工作表行（用于大文件 / 内存敏感场景）。offset 起始行，limit 读取行数；columns 可选，只读指定列。返回 chunk 数据 + total_rows。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "offset": {"type": "integer", "default": 0, "minimum": 0},
                "limit": {"type": "integer", "default": 1000, "minimum": 1},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：只读这些列",
                },
            },
            "required": ["file_id", "sheet"],
        },
    },
    {
        "name": "tablex_decrypt",
        "description": "用密码解密加密的 .xlsx 文件。解密后写入 session 的工作表。密码错误时返回 decrypt_failed 错误码。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "加密文件的 file_id"},
                "password": {"type": "string", "description": "解密密码"},
                "output_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "结果文件的人类可读名字（必填，会作为右侧预览器 tab 标题）",
                },
            },
            "required": ["file_id", "password", "output_name"],
        },
    },
    {
        "name": "tablex_analyze",
        "description": "高级分析。operation=correlation 计算相关性矩阵（pearson/spearman）；operation=outlier 异常检测（z-score 或 IQR）；operation=regression 最小二乘线性回归；operation=moving_avg 移动平均（rolling window）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "operation": {
                    "type": "string",
                    "enum": ["correlation", "outlier", "regression", "moving_avg"],
                },
                "params": {
                    "type": "object",
                    "description": "操作相关参数",
                    "properties": {
                        "method": {
                            "type": "string",
                            "description": "correlation: pearson/spearman；outlier: zscore/iqr",
                        },
                        "columns": {"type": "array", "items": {"type": "string"}},
                        "x": {"type": "string", "description": "regression 自变量"},
                        "y": {"type": "string", "description": "regression 因变量"},
                        "column": {"type": "string", "description": "moving_avg 目标列"},
                        "window": {"type": "integer", "default": 7, "description": "moving_avg 窗口"},
                        "threshold": {
                            "type": "number",
                            "default": 3.0,
                            "description": "outlier 阈值（z-score 或 IQR 倍数）",
                        },
                    },
                },
            },
            "required": ["file_id", "sheet", "operation"],
        },
    },
    {
        "name": "tablex_formula_graph",
        "description": "提取工作表中所有公式并构建依赖图（简单 A1 引用形式）。返回 formulas + 依赖图 + 循环依赖报告。cell 可选，指定时只返回该 cell 的上游 / 下游。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "cell": {
                    "type": "string",
                    "description": "可选：只看某个 cell 的依赖（如 A1）",
                },
            },
            "required": ["file_id", "sheet"],
        },
    },
    {
        "name": "tablex_template_fill",
        "description": "把 {{key}} 占位符替换为 data[key] 的值，生成新的 xlsx。返回替换次数 + 缺失 key 列表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "template_file_id": {"type": "string", "description": "模板文件 ID"},
                "data": {
                    "type": "object",
                    "description": "要填的数据，如 {\"name\": \"张三\", \"date\": \"2026-09-16\"}",
                },
                "sheet": {
                    "type": "string",
                    "description": "可选：模板里的工作表名；省略则取第一个",
                },
            },
            "required": ["template_file_id", "data"],
        },
    },
    {
        "name": "tablex_export_styled",
        "description": "带格式导出：粗体 / 颜色表头 + 高亮规则 + 冻结首行 + 列宽自适应 + 合并单元格。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "style": {
                    "type": "object",
                    "properties": {
                        "header": {
                            "type": "object",
                            "properties": {
                                "bold": {"type": "boolean", "default": False},
                                "bg_color": {"type": "string", "description": "无 # 前缀的 hex"},
                                "font_color": {"type": "string", "description": "无 # 前缀的 hex"},
                            },
                        },
                        "highlight_rules": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "condition": {
                                        "type": "string",
                                        "description": "如 >1000, ==\"VIP\", <500",
                                    },
                                    "bg_color": {"type": "string"},
                                },
                                "required": ["column", "condition", "bg_color"],
                            },
                        },
                        "freeze_header": {"type": "boolean", "default": False},
                        "auto_column_width": {"type": "boolean", "default": False},
                        "merge_cells": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "range": {"type": "string", "description": "如 A1:E1"},
                                    "value": {"type": "string"},
                                },
                                "required": ["range", "value"],
                            },
                        },
                    },
                },
                "output_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "结果文件的人类可读名字（必填，会作为右侧预览器 tab 标题）",
                },
            },
            "required": ["file_id", "sheet", "style", "output_name"],
        },
    },
    {
        "name": "tablex_split_by_column",
        "description": "按指定列的唯一值把工作表拆成多个 sheet（每个唯一值一个 sheet，sheet 名 = 该值的字符串）。返回 output_name 和创建的 sheets 列表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "sheet": {"type": "string"},
                "group_column": {
                    "type": "string",
                    "description": "按此列的唯一值拆分",
                },
                "output_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "结果文件的人类可读名字（必填，会作为右侧预览器 tab 标题）",
                },
            },
            "required": ["file_id", "sheet", "group_column", "output_name"],
        },
    },
]
