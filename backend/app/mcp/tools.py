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
]