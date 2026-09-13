import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
export function TaskPanel({ requestText, onRequestChange, onSubmit, disabled, loading }) {
    const [local, setLocal] = useState(requestText);
    return (_jsxs("section", { className: "panel", "aria-label": "\u4EFB\u52A1\u8F93\u5165", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u4EFB\u52A1" }) }), _jsx("div", { className: "panel-body", children: _jsxs("form", { onSubmit: (e) => {
                        e.preventDefault();
                        onRequestChange(local);
                        onSubmit(local);
                    }, children: [_jsx("textarea", { "data-testid": "task-input", value: local, maxLength: 2000, rows: 4, disabled: disabled, placeholder: "\u4F8B\u5982\uFF1A\u68C0\u67E5\u6570\u636E\u95EE\u9898\uFF0C\u7EDF\u4E00\u91D1\u989D\u683C\u5F0F\u5E76\u6309\u90E8\u95E8\u6C47\u603B", onChange: (e) => setLocal(e.target.value) }), _jsx("div", { className: "actions", children: _jsx("button", { type: "submit", className: "primary", "data-testid": "plan-button", disabled: disabled || !local.trim() || loading, children: loading ? "规划中..." : "生成执行计划" }) })] }) })] }));
}
