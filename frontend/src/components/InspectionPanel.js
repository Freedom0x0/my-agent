import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const severityLabel = {
    info: "提示",
    warning: "警告",
    error: "错误",
};
export function InspectionPanel({ files }) {
    if (files.length === 0) {
        return (_jsxs("section", { className: "panel", "aria-label": "\u4F53\u68C0\u7ED3\u679C", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u4F53\u68C0" }) }), _jsx("div", { className: "panel-body", children: _jsx("p", { className: "empty-state", children: "\u5C1A\u672A\u4E0A\u4F20\u6587\u4EF6" }) })] }));
    }
    return (_jsxs("section", { className: "panel", "aria-label": "\u4F53\u68C0\u7ED3\u679C", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u4F53\u68C0" }) }), _jsx("div", { className: "panel-body", children: files.flatMap((f) => f.sheets.map((s) => (_jsxs("article", { className: "sheet-summary", "data-testid": "inspection-sheet", children: [_jsx("h3", { children: s.displayName }), _jsxs("p", { className: "meta", children: [s.rowCount, " \u884C \u00D7 ", s.columnCount, " \u5217"] }), _jsx("ul", { className: "column-list", children: s.columns.map((c) => (_jsxs("li", { children: [_jsx("span", { children: c.name }), _jsxs("span", { className: "meta", children: [c.inferredType, " \u00B7 \u7A7A\u503C ", c.nullCount, " \u00B7 \u552F\u4E00 ", c.uniqueCount] })] }, c.name))) }), s.issues.length > 0 && (_jsx("ul", { className: "issue-list", "data-testid": "issue-list", children: s.issues.map((issue, idx) => (_jsxs("li", { "data-severity": issue.severity, children: [_jsxs("strong", { children: ["[", severityLabel[issue.severity], "]"] }), " ", issue.message, issue.column && _jsxs("span", { className: "meta", children: ["\u5B57\u6BB5\uFF1A", issue.column] })] }, `${issue.code}-${idx}`))) }))] }, s.ref)))) })] }));
}
