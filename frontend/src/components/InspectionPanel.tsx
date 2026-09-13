import type { FileItem, IssueSummary } from "../domain/models";

type Props = {
  files: FileItem[];
};

const severityLabel: Record<IssueSummary["severity"], string> = {
  info: "提示",
  warning: "警告",
  error: "错误",
};

export function InspectionPanel({ files }: Props) {
  if (files.length === 0) {
    return (
      <section className="panel" aria-label="体检结果">
        <header className="panel-header">
          <h2>体检</h2>
        </header>
        <div className="panel-body">
          <p className="empty-state">尚未上传文件</p>
        </div>
      </section>
    );
  }
  return (
    <section className="panel" aria-label="体检结果">
      <header className="panel-header">
        <h2>体检</h2>
      </header>
      <div className="panel-body">
        {files.flatMap((f) =>
          f.sheets.map((s) => (
            <article key={s.ref} className="sheet-summary" data-testid="inspection-sheet">
              <h3>{s.displayName}</h3>
              <p className="meta">
                {s.rowCount} 行 × {s.columnCount} 列
              </p>
              <ul className="column-list">
                {s.columns.map((c) => (
                  <li key={c.name}>
                    <span>{c.name}</span>
                    <span className="meta">
                      {c.inferredType} · 空值 {c.nullCount} · 唯一 {c.uniqueCount}
                    </span>
                  </li>
                ))}
              </ul>
              {s.issues.length > 0 && (
                <ul className="issue-list" data-testid="issue-list">
                  {s.issues.map((issue, idx) => (
                    <li key={`${issue.code}-${idx}`} data-severity={issue.severity}>
                      <strong>[{severityLabel[issue.severity]}]</strong> {issue.message}
                      {issue.column && <span className="meta">字段：{issue.column}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          )),
        )}
      </div>
    </section>
  );
}