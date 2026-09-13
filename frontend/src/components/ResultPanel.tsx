import type { ExecutionView } from "../domain/models";
import { api } from "../api/httpClient";

type Props = {
  result: ExecutionView | null;
};

export function ResultPanel({ result }: Props) {
  if (!result) {
    return (
      <section className="panel" aria-label="执行结果">
        <header className="panel-header">
          <h2>结果</h2>
        </header>
        <div className="panel-body">
          <p className="empty-state">尚未执行计划</p>
        </div>
      </section>
    );
  }
  return (
    <section className="panel" aria-label="执行结果">
      <header className="panel-header">
        <h2>结果</h2>
      </header>
      <div className="panel-body" data-testid="result-panel">
        <ul className="metric-list">
          {Object.entries(result.metrics).map(([k, v]) => (
            <li key={k}>
              <span>{k}</span>
              <strong>{String(v)}</strong>
            </li>
          ))}
        </ul>
        <h3>结论</h3>
        <ul className="conclusion-list" data-testid="conclusion-list">
          {result.conclusions.map((c, idx) => (
            <li key={`${c.stepId}-${idx}`} data-severity={c.severity}>
              <strong>{c.text}</strong>
              {c.value !== null && <span className="meta">值：{String(c.value)}</span>}
              <span className="meta">来源步骤：{c.stepId}</span>
            </li>
          ))}
        </ul>
        <h3>输出工作表</h3>
        <ul className="sheet-list">
          {result.sheets.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        <div className="actions">
          <a
            data-testid="download-link"
            href={api.downloadUrl(result.outputId)}
            download
            className="primary"
          >
            下载处理后的 Excel
          </a>
        </div>
      </div>
    </section>
  );
}