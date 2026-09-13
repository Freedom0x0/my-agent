import type { FileItem } from "../domain/models";

type Props = {
  files: FileItem[];
  onUpload: (file: File) => void;
  disabled?: boolean;
};

export function FilePanel({ files, onUpload, disabled }: Props) {
  return (
    <section className="panel" aria-label="文件与工作表">
      <header className="panel-header">
        <h2>文件</h2>
      </header>
      <div className="panel-body">
        <label className="upload-label">
          <input
            data-testid="file-input"
            type="file"
            accept=".xlsx,.xls,.csv"
            disabled={disabled}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = "";
            }}
          />
          <span>选择 Excel/CSV 文件</span>
        </label>
        {files.length === 0 ? (
          <p className="empty-state">尚未上传文件</p>
        ) : (
          <ul className="file-list" data-testid="file-list">
            {files.map((f) => (
              <li key={f.id} className="file-item" data-testid="file-item">
                <strong>{f.name}</strong>
                <div className="meta">{Math.round(f.sizeBytes / 1024)} KB</div>
                <ul className="sheet-list">
                  {f.sheets.map((s) => (
                    <li key={s.ref}>
                      <span>{s.displayName}</span>
                      <span className="meta">
                        {s.rowCount} 行 × {s.columnCount} 列
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}