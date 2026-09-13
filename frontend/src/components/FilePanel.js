import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function FilePanel({ files, onUpload, disabled }) {
    return (_jsxs("section", { className: "panel", "aria-label": "\u6587\u4EF6\u4E0E\u5DE5\u4F5C\u8868", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u6587\u4EF6" }) }), _jsxs("div", { className: "panel-body", children: [_jsxs("label", { className: "upload-label", children: [_jsx("input", { "data-testid": "file-input", type: "file", accept: ".xlsx,.xls,.csv", disabled: disabled, onChange: (e) => {
                                    const f = e.target.files?.[0];
                                    if (f)
                                        onUpload(f);
                                    e.target.value = "";
                                } }), _jsx("span", { children: "\u9009\u62E9 Excel/CSV \u6587\u4EF6" })] }), files.length === 0 ? (_jsx("p", { className: "empty-state", children: "\u5C1A\u672A\u4E0A\u4F20\u6587\u4EF6" })) : (_jsx("ul", { className: "file-list", "data-testid": "file-list", children: files.map((f) => (_jsxs("li", { className: "file-item", "data-testid": "file-item", children: [_jsx("strong", { children: f.name }), _jsxs("div", { className: "meta", children: [Math.round(f.sizeBytes / 1024), " KB"] }), _jsx("ul", { className: "sheet-list", children: f.sheets.map((s) => (_jsxs("li", { children: [_jsx("span", { children: s.displayName }), _jsxs("span", { className: "meta", children: [s.rowCount, " \u884C \u00D7 ", s.columnCount, " \u5217"] })] }, s.ref))) })] }, f.id))) }))] })] }));
}
