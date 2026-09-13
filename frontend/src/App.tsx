import { FilePanel } from "./components/FilePanel";
import { InspectionPanel } from "./components/InspectionPanel";
import { PlanPanel } from "./components/PlanPanel";
import { ResultPanel } from "./components/ResultPanel";
import { TaskPanel } from "./components/TaskPanel";
import { useWorkflow } from "./hooks/useWorkflow";

export function App() {
  const { state, dispatch, upload, plan, execute } = useWorkflow();

  const fileIds = state.files.map((f) => f.id);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>表析 Agent</h1>
      </header>
      {state.error && (
        <div className="app-error" role="alert" data-testid="app-error">
          <span>{state.error.message}</span>
          <button type="button" onClick={() => dispatch({ type: "CLEAR_ERROR" })}>
            关闭
          </button>
        </div>
      )}
      <main className="workspace">
        <div className="column">
          <FilePanel
            files={state.files}
            onUpload={(file) => {
              dispatch({ type: "UPLOAD_START" });
              void upload(file);
            }}
            disabled={state.status === "uploading"}
          />
          <InspectionPanel files={state.files} />
        </div>
        <div className="column">
          <TaskPanel
            requestText={state.requestText}
            onRequestChange={(text) => dispatch({ type: "SET_REQUEST", request: text })}
            onSubmit={(text) => {
              if (fileIds.length === 0 || !text.trim()) return;
              dispatch({ type: "PLAN_START" });
              void plan(fileIds, text.trim());
            }}
            disabled={fileIds.length === 0}
            loading={state.status === "planning"}
          />
          <PlanPanel
            plan={state.plan}
            loading={state.status === "executing"}
            confirmed={state.status === "completed"}
            onConfirm={() => {
              if (!state.plan) return;
              const token = state.plan.requiresConfirmation ? `confirm:${state.plan.id}` : null;
              dispatch({ type: "EXECUTE_START" });
              void execute(fileIds, state.plan, token);
            }}
          />
        </div>
        <div className="column">
          <ResultPanel result={state.result} />
        </div>
      </main>
    </div>
  );
}