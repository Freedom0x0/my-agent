import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { FilePanel } from "./components/FilePanel";
import { InspectionPanel } from "./components/InspectionPanel";
import { PlanPanel } from "./components/PlanPanel";
import { ResultPanel } from "./components/ResultPanel";
import { TaskPanel } from "./components/TaskPanel";
import { useWorkflow } from "./hooks/useWorkflow";
export function App() {
    const { state, dispatch, upload, plan, execute } = useWorkflow();
    const fileIds = state.files.map((f) => f.id);
    return (_jsxs("div", { className: "app-shell", children: [_jsx("header", { className: "app-header", children: _jsx("h1", { children: "\u8868\u6790 Agent" }) }), state.error && (_jsxs("div", { className: "app-error", role: "alert", "data-testid": "app-error", children: [_jsx("span", { children: state.error.message }), _jsx("button", { type: "button", onClick: () => dispatch({ type: "CLEAR_ERROR" }), children: "\u5173\u95ED" })] })), _jsxs("main", { className: "workspace", children: [_jsxs("div", { className: "column", children: [_jsx(FilePanel, { files: state.files, onUpload: (file) => {
                                    dispatch({ type: "UPLOAD_START" });
                                    void upload(file);
                                }, disabled: state.status === "uploading" }), _jsx(InspectionPanel, { files: state.files })] }), _jsxs("div", { className: "column", children: [_jsx(TaskPanel, { requestText: state.requestText, onRequestChange: (text) => dispatch({ type: "SET_REQUEST", request: text }), onSubmit: (text) => {
                                    if (fileIds.length === 0 || !text.trim())
                                        return;
                                    dispatch({ type: "PLAN_START" });
                                    void plan(fileIds, text.trim());
                                }, disabled: fileIds.length === 0, loading: state.status === "planning" }), _jsx(PlanPanel, { plan: state.plan, loading: state.status === "executing", confirmed: state.status === "completed", onConfirm: () => {
                                    if (!state.plan)
                                        return;
                                    const token = state.plan.requiresConfirmation ? `confirm:${state.plan.id}` : null;
                                    dispatch({ type: "EXECUTE_START" });
                                    void execute(fileIds, state.plan, token);
                                } })] }), _jsx("div", { className: "column", children: _jsx(ResultPanel, { result: state.result }) })] })] }));
}
