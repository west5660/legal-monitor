import { startTransition, useEffect, useMemo, useRef, useState } from "react";

interface Props {
  headers: string[];
  rows: string[][];
  truncated?: boolean;
}

export default function ExcelViewer({ headers, rows, truncated }: Props) {
  const [visibleCols, setVisibleCols] = useState<Set<number>>(
    () => new Set(headers.map((_, i) => i))
  );
  const [filterDraft, setFilterDraft] = useState<Record<number, string>>({});
  const [filters, setFilters] = useState<Record<number, string>>({});
  const [showFilters, setShowFilters] = useState(false);
  const [showColumns, setShowColumns] = useState(false);
  const [fitWidth, setFitWidth] = useState(true);
  const columnsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setFilters(filterDraft), 200);
    return () => window.clearTimeout(t);
  }, [filterDraft]);

  useEffect(() => {
    if (!showColumns) return;
    const onClick = (e: MouseEvent) => {
      if (columnsRef.current && !columnsRef.current.contains(e.target as Node)) {
        setShowColumns(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [showColumns]);

  const colIndices = useMemo(
    () => headers.map((_, i) => i).filter((i) => visibleCols.has(i)),
    [headers, visibleCols]
  );

  const filteredRows = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => v.trim());
    if (!active.length) return rows;
    return rows.filter((row) =>
      active.every(([col, text]) => {
        const val = String(row[Number(col)] ?? "").toLowerCase();
        return val.includes(text.trim().toLowerCase());
      })
    );
  }, [rows, filters]);

  const toggleColumn = (index: number) => {
    startTransition(() => {
      setVisibleCols((prev) => {
        const next = new Set(prev);
        if (next.has(index)) {
          if (next.size <= 1) return prev;
          next.delete(index);
        } else {
          next.add(index);
        }
        return next;
      });
    });
  };

  const showAllColumns = () => {
    startTransition(() => setVisibleCols(new Set(headers.map((_, i) => i))));
  };

  const clearFilters = () => {
    setFilterDraft({});
    setFilters({});
  };

  const hasFilters = Object.values(filterDraft).some((v) => v.trim());

  return (
    <div className="excel-viewer">
      <div className="excel-toolbar">
        <button
          type="button"
          className={`btn btn-ghost excel-tool-btn ${showFilters ? "excel-tool-btn--active" : ""}`}
          onClick={() => setShowFilters((v) => !v)}
        >
          Фильтры
        </button>

        <div className="excel-tool-dropdown" ref={columnsRef}>
          <button
            type="button"
            className={`btn btn-ghost excel-tool-btn ${showColumns ? "excel-tool-btn--active" : ""}`}
            onClick={() => setShowColumns((v) => !v)}
          >
            Столбцы ({colIndices.length}/{headers.length})
          </button>
          {showColumns && (
            <div className="excel-dropdown-panel glass-strong">
              <div className="excel-dropdown-head">
                <span>Отображаемые столбцы</span>
                <button type="button" className="btn btn-ghost" onClick={showAllColumns}>
                  Все
                </button>
              </div>
              <div className="excel-column-list">
                {headers.map((h, i) => (
                  <label key={i} className="excel-column-item">
                    <input
                      type="checkbox"
                      checked={visibleCols.has(i)}
                      onChange={() => toggleColumn(i)}
                    />
                    <span title={h || `Столбец ${i + 1}`}>{h || `Столбец ${i + 1}`}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          className={`btn btn-ghost excel-tool-btn ${fitWidth ? "excel-tool-btn--active" : ""}`}
          onClick={() => startTransition(() => setFitWidth((v) => !v))}
          title={fitWidth ? "Показать полную ширину столбцов" : "Уместить таблицу по ширине окна"}
        >
          {fitWidth ? "По ширине окна" : "Полная ширина"}
        </button>

        {hasFilters && (
          <button type="button" className="btn btn-ghost excel-tool-btn" onClick={clearFilters}>
            Сбросить фильтры
          </button>
        )}

        <span className="excel-stats">
          {filteredRows.length} из {rows.length} строк
          {colIndices.length < headers.length && ` · ${colIndices.length} столбцов`}
        </span>
      </div>

      <div className="excel-scroll">
        <table className={`xlsx-table ${fitWidth ? "xlsx-table--fit" : "xlsx-table--wide"}`}>
          <thead>
            <tr>
              {colIndices.map((i) => (
                <th key={i} title={headers[i]}>
                  {headers[i] || `Столбец ${i + 1}`}
                </th>
              ))}
            </tr>
            {showFilters && (
              <tr className="xlsx-filter-row">
                {colIndices.map((i) => (
                  <th key={i}>
                    <input
                      type="text"
                      className="xlsx-filter-input"
                      placeholder="Фильтр…"
                      value={filterDraft[i] ?? ""}
                      onChange={(e) =>
                        setFilterDraft((prev) => ({ ...prev, [i]: e.target.value }))
                      }
                    />
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {filteredRows.map((row, ri) => (
              <tr key={ri}>
                {colIndices.map((ci) => (
                  <td key={ci} title={String(row[ci] ?? "")}>
                    {row[ci] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        {filteredRows.length === 0 && (
          <p className="excel-empty">Нет строк по заданным фильтрам</p>
        )}
      </div>

      {truncated && (
        <p className="hint-dblclick">Показаны первые {rows.length} строк файла</p>
      )}
    </div>
  );
}
