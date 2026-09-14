import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type ColumnFilterState = {
  search: string;
  picks: string[];
  blank: "any" | "empty" | "not_empty";
};

export const EMPTY_COLUMN_FILTER: ColumnFilterState = {
  search: "",
  picks: [],
  blank: "any",
};

const UNIQUE_CAP = 200;

export function isColumnFilterActive(f: ColumnFilterState): boolean {
  return f.blank !== "any" || f.picks.length > 0 || !!f.search.trim();
}

export function matchColumnFilter(value: string, filter: ColumnFilterState): boolean {
  const v = (value ?? "").trim();
  const empty = !v || v === "—";

  if (filter.blank === "empty") return empty;
  if (filter.blank === "not_empty") return !empty;

  if (filter.picks.length > 0 && !filter.picks.includes(v)) {
    return false;
  }
  if (filter.search.trim()) {
    return v.toLowerCase().includes(filter.search.trim().toLowerCase());
  }
  return true;
}

interface Props {
  values: string[];
  filter: ColumnFilterState;
  onChange: (next: ColumnFilterState) => void;
  placeholder?: string;
}

export default function ColumnFilter({ values, filter, onChange, placeholder = "Фильтр…" }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [panelPos, setPanelPos] = useState({ top: 0, left: 0, width: 260 });
  const rootRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const { unique, truncated } = useMemo(() => {
    if (!open) return { unique: [] as string[], truncated: false };
    const set = new Set<string>();
    for (const v of values) {
      const t = (v ?? "").trim();
      if (t) set.add(t);
      if (set.size >= UNIQUE_CAP) break;
    }
    const sorted = [...set].sort((a, b) => a.localeCompare(b, "ru"));
    return { unique: sorted, truncated: set.size >= UNIQUE_CAP };
  }, [values, open]);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return unique.slice(0, 80);
    return unique.filter((v) => v.toLowerCase().includes(q)).slice(0, 80);
  }, [unique, query]);

  const updatePanelPos = () => {
    const btn = btnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const width = Math.max(rect.width + 180, 260);
    let left = rect.right - width;
    if (left < 8) left = 8;
    if (left + width > window.innerWidth - 8) {
      left = window.innerWidth - width - 8;
    }
    setPanelPos({
      top: rect.bottom + 6,
      left,
      width,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePanelPos();
    window.addEventListener("resize", updatePanelPos);
    window.addEventListener("scroll", updatePanelPos, true);
    return () => {
      window.removeEventListener("resize", updatePanelPos);
      window.removeEventListener("scroll", updatePanelPos, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const timer = window.setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("mousedown", onDoc);
    };
  }, [open]);

  const togglePick = (val: string) => {
    const has = filter.picks.includes(val);
    onChange({
      ...filter,
      picks: has ? filter.picks.filter((p) => p !== val) : [...filter.picks, val],
      blank: "any",
    });
  };

  const active = isColumnFilterActive(filter);

  const panel =
    open &&
    createPortal(
      <div
        ref={panelRef}
        className="col-filter-panel glass-strong col-filter-panel--portal"
        style={{
          position: "fixed",
          top: panelPos.top,
          left: panelPos.left,
          width: panelPos.width,
          zIndex: 5000,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="col-filter-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => onChange({ ...filter, picks: [...unique], blank: "any" })}
          >
            Все
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => onChange({ ...EMPTY_COLUMN_FILTER })}
          >
            Сброс
          </button>
        </div>
        <div className="col-filter-special">
          <label>
            <input
              type="radio"
              name={`blank-${placeholder}`}
              checked={filter.blank === "any" && filter.picks.length === 0}
              onChange={() => onChange({ ...filter, blank: "any", picks: [] })}
            />
            Все значения
          </label>
          <label>
            <input
              type="radio"
              name={`blank-${placeholder}`}
              checked={filter.blank === "not_empty"}
              onChange={() => onChange({ ...filter, blank: "not_empty", picks: [] })}
            />
            Не пустые
          </label>
          <label>
            <input
              type="radio"
              name={`blank-${placeholder}`}
              checked={filter.blank === "empty"}
              onChange={() => onChange({ ...filter, blank: "empty", picks: [] })}
            />
            Пустые
          </label>
        </div>
        <input
          className="xlsx-filter-input"
          placeholder="Поиск в списке…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="col-filter-list">
          {list.map((val) => (
            <label key={val} className="col-filter-item" title={val}>
              <input
                type="checkbox"
                checked={filter.picks.includes(val)}
                onChange={() => togglePick(val)}
              />
              <span>{val}</span>
            </label>
          ))}
          {list.length === 0 && <p className="col-filter-empty">Нет значений</p>}
          {truncated && !query && (
            <p className="col-filter-hint">Показаны первые {UNIQUE_CAP}. Уточните поиск или введите текст выше.</p>
          )}
        </div>
      </div>,
      document.body
    );

  return (
    <div className="col-filter" ref={rootRef}>
      <div className="col-filter-row">
        <input
          className="xlsx-filter-input"
          placeholder={placeholder}
          value={filter.search}
          onChange={(e) => onChange({ ...filter, search: e.target.value, blank: "any" })}
        />
        <button
          ref={btnRef}
          type="button"
          className={`col-filter-btn${active || open ? " col-filter-btn--active" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((v) => !v);
          }}
          title="Фильтр по списку"
          aria-expanded={open}
        >
          ▾
        </button>
      </div>
      {panel}
    </div>
  );
}
