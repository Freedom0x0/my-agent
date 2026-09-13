import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
export function PlanPanel({ plan, onConfirm, loading, confirmed }) {
    const [confirming, setConfirming] = useState(false);
    if (!plan) {
        return (_jsxs("section", { className: "panel", "aria-label": "\u6267\u884C\u8BA1\u5212", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u6267\u884C\u8BA1\u5212" }) }), _jsx("div", { className: "panel-body", children: _jsx("p", { className: "empty-state", children: "\u5C1A\u672A\u751F\u6210\u8BA1\u5212" }) })] }));
    }
    const showConfirmButton = !confirmed && !loading;
    return (_jsxs("section", { className: "panel", "aria-label": "\u6267\u884C\u8BA1\u5212", children: [_jsx("header", { className: "panel-header", children: _jsx("h2", { children: "\u6267\u884C\u8BA1\u5212" }) }), _jsxs("div", { className: "panel-body", "data-testid": "plan-panel", children: [_jsx("p", { children: plan.explanation }), _jsx("ol", { className: "step-list", children: plan.steps.map((step, idx) => (_jsxs("li", { children: [_jsx("strong", { children: step.description }), step.columns.length > 0 && (_jsxs("span", { className: "meta", children: ["\u5B57\u6BB5\uFF1A", step.columns.join("、")] })), step.outputSheet && (_jsxs("span", { className: "meta", children: ["\u8F93\u51FA\uFF1A", step.outputSheet] }))] }, `${step.kind}-${idx}`))) }), _jsxs("p", { className: "meta", children: ["\u8F93\u51FA\u5DE5\u4F5C\u8868\uFF1A", plan.outputNames.join("、")] }), plan.requiresConfirmation && (_jsx("p", { className: "warning", "data-testid": "confirmation-warning", children: "\u8BE5\u8BA1\u5212\u4F1A\u4FEE\u6539\u6216\u5220\u9664\u6570\u636E\uFF0C\u8BF7\u786E\u8BA4\u5F71\u54CD\u8303\u56F4\u540E\u7EE7\u7EED\u3002" })), showConfirmButton && (_jsx("div", { className: "actions", children: _jsx("button", { type: "button", className: "primary", "data-testid": "execute-button", disabled: loading, onClick: () => {
                                if (plan.requiresConfirmation && !confirming) {
                                    setConfirming(true);
                                    return;
                                }
                                onConfirm();
                            }, children: plan.requiresConfirmation
                                ? confirming
                                    ? "再次点击确认执行"
                                    : "执行计划"
                                : "执行计划" }) }))] })] }));
}
