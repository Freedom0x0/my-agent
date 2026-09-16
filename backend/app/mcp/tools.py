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
        "description": "将当前 session 中所有处理后的工作表写入一个新的 xlsx 文件，返回 output_id 供前端下载。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "主文件 ID（用于命名审计来源，可省略）",
                },
            },
            "required": [],
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
]