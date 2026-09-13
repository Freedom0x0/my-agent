import { useState } from "react";

import type { PlanView } from "../domain/models";

type Props = {
  plan: PlanView | null;
  onConfirm: () => void;
  loading?: boolean;
  confirmed?: boolean;
};

export function PlanPanel({ plan, onConfirm, loading, confirmed }: Props) {
  const [confirming, setConfirming] = useState(false);
  if (!plan) {
    return (
      <section className="panel" aria-label="执行计划">
        <header className="panel-header">
          <h2>执行计划</h2>
        </header>
        <div className="panel-body">
          <p className="empty-state">尚未生成计划</p>
        </div>
      </section>
    );
  }
  const showConfirmButton = !confirmed && !loading;
  return (
    <section className="panel" aria-label="执行计划">
      <header className="panel-header">
        <h2>执行计划</h2>
      </header>
      <div className="panel-body" data-testid="plan-panel">
        <p>{plan.explanation}</p>
        <ol className="step-list">
          {plan.steps.map((step, idx) => (
            <li key={`${step.kind}-${idx}`}>
              <strong>{step.description}</strong>
              {step.columns.length > 0 && (
                <span className="meta">字段：{step.columns.join("、")}</span>
              )}
              {step.outputSheet && (
                <span className="meta">输出：{step.outputSheet}</span>
              )}
            </li>
          ))}
        </ol>
        <p className="meta">输出工作表：{plan.outputNames.join("、")}</p>
        {plan.requiresConfirmation && (
          <p className="warning" data-testid="confirmation-warning">
            该计划会修改或删除数据，请确认影响范围后继续。
          </p>
        )}
        {showConfirmButton && (
          <div className="actions">
            <button
              type="button"
              className="primary"
              data-testid="execute-button"
              disabled={loading}
              onClick={() => {
                if (plan.requiresConfirmation && !confirming) {
                  setConfirming(true);
                  return;
                }
                onConfirm();
              }}
            >
              {plan.requiresConfirmation
                ? confirming
                  ? "再次点击确认执行"
                  : "执行计划"
                : "执行计划"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}