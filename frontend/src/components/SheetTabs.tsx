type Props = {
  sheets: string[];
  active: string;
  onSelect: (name: string) => void;
  onDownload?: () => void;
};

export function SheetTabs({ sheets, active, onSelect, onDownload }: Props) {
  if (sheets.length <= 1 && !onDownload) return null;
  return (
    <div className="sheet-tabs" role="tablist" data-testid="sheet-tabs">
      {sheets.map((name) => (
        <button
          type="button"
          role="tab"
          key={name}
          aria-selected={name === active}
          className={`sheet-tab ${name === active ? "is-active" : ""}`}
          data-testid="sheet-tab"
          onClick={() => onSelect(name)}
        >
          <span className="sheet-tab-name">{name}</span>
          {onDownload && (
            <span
              role="button"
              tabIndex={0}
              aria-label="下载该 Excel"
              className="sheet-tab-download"
              onClick={(e) => {
                e.stopPropagation();
                onDownload();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onDownload();
                }
              }}
            >
              ⬇
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
