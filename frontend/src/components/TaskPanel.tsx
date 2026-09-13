import { useState, type FormEvent } from "react";

type Props = {
  requestText: string;
  onRequestChange: (text: string) => void;
  onSubmit: (text: string) => void;
  disabled?: boolean;
  loading?: boolean;
};

export function TaskPanel({ requestText, onRequestChange, onSubmit, disabled, loading }: Props) {
  const [local, setLocal] = useState(requestText);
  return (
    <section className="panel" aria-label="任务输入">
      <header className="panel-header">
        <h2>任务</h2>
      </header>
      <div className="panel-body">
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            onRequestChange(local);
            onSubmit(local);
          }}
        >
          <textarea
            data-testid="task-input"
            value={local}
            maxLength={2000}
            rows={4}
            disabled={disabled}
            placeholder="例如：检查数据问题，统一金额格式并按部门汇总"
            onChange={(e) => setLocal(e.target.value)}
          />
          <div className="actions">
            <button
              type="submit"
              className="primary"
              data-testid="plan-button"
              disabled={disabled || !local.trim() || loading}
            >
              {loading ? "规划中..." : "生成执行计划"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}