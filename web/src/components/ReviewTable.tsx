import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ReviewRow } from "../api/client";
import ColumnFilter, {
  ColumnFilterState,
  EMPTY_COLUMN_FILTER,
  isColumnFilterActive,
  matchColumnFilter,
} from "./ColumnFilter";

const ROW_HEIGHT = 88;
const OVERSCAN = 8;

export type ReviewColumnFilters = {
  date: ColumnFilterState;
  source: ColumnFilterState;
  profile: ColumnFilterState;
  title: ColumnFilterState;
  brief: ColumnFilterState;
  stage: ColumnFilterState;
};

const EMPTY_FILTERS: ReviewColumnFilters = {
  date: { ...EMPTY_COLUMN_FILTER },
  source: { ...EMPTY_COLUMN_FILTER },
  profile: { ...EMPTY_COLUMN_FILTER },
  title: { ...EMPTY_COLUMN_FILTER },
  brief: { ...EMPTY_COLUMN_FILTER },
  stage: { ...EMPTY_COLUMN_FILTER },
};

function rowBrief(row: ReviewRow): string {
  const b = row.brief_summary || row.analysis_preview || "";
  if (b && b !== "—") return b;
  return row.title || "—";
}

function filterRows(rows: ReviewRow[], filters: ReviewColumnFilters): ReviewRow[] {
  return rows.filter((r) => {
    const brief = rowBrief(r);
    return (
      matchColumnFilter(r.register_date ?? "", filters.date) &&
      matchColumnFilter(r.source, filters.source) &&
      matchColumnFilter(r.profile_name, filters.profile) &&
      matchColumnFilter(r.title, filters.title) &&
      matchColumnFilter(brief, filters.brief) &&
      matchColumnFilter(r.stage || "", filters.stage)
    );
  });
}

interface ReviewRowItemProps {
  row: ReviewRow;
  isSelected: boolean;
  onToggle: (rowId: string) => void;
  onOpenDetail?: (documentId: number) => void;
  style: React.CSSProperties;
}

const ReviewRowItem = memo(function ReviewRowItem({
  row,
  isSelected,
  onToggle,
  onOpenDetail,
  style,
}: ReviewRowItemProps) {
  const brief = rowBrief(row);
  return (
    <div
      className={`review-row${isSelected ? " review-row--selected" : ""}`}
      style={style}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a, input, button")) return;
        onToggle(row.row_id);
      }}
      onDoubleClick={(e) => {
        if ((e.target as HTMLElement).closest("a, input, button")) return;
        onOpenDetail?.(row.document_id);
      }}
    >
      <div className="review-cell review-cell--check">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggle(row.row_id)}
          onClick={(e) => e.stopPropagation()}
        />
      </div>
      <div className="review-cell review-cell--date">{row.register_date ?? "—"}</div>
      <div className="review-cell review-cell--source">
        <span className="badge badge-blue">{row.source}</span>
      </div>
      <div className="review-cell review-cell--profile" title={row.profile_name}>
        {row.profile_name}
      </div>
      <div className="review-cell review-cell--title" title={row.title}>
        {row.url ? (
          <a href={row.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
            {row.title}
          </a>
        ) : (
          row.title
        )}
      </div>
      <div className="review-cell review-cell--brief" title={brief}>
        {brief}
      </div>
      <div className="review-cell review-cell--stage">{row.stage || "—"}</div>
    </div>
  );
});

interface Props {
  rows: ReviewRow[];
  selected: Set<string>;
  onToggle: (rowId: string) => void;
  onToggleVisible: (rowIds: string[], select: boolean) => void;
  onOpenDetail?: (documentId: number) => void;
}

export default function ReviewTable({ rows, selected, onToggle, onToggleVisible, onOpenDetail }: Props) {
  const [filters, setFilters] = useState<ReviewColumnFilters>(EMPTY_FILTERS);
  const deferredFilters = useDeferredValue(filters);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(640);

  const columnValues = useMemo(
    () => ({
      date: rows.map((r) => r.register_date ?? ""),
      source: rows.map((r) => r.source),
      profile: rows.map((r) => r.profile_name),
      title: rows.map((r) => r.title),
      brief: rows.map((r) => rowBrief(r)),
      stage: rows.map((r) => r.stage || ""),
    }),
    [rows]
  );

  const filtered = useMemo(
    () => filterRows(rows, deferredFilters),
    [rows, deferredFilters]
  );

  const totalHeight = filtered.length * ROW_HEIGHT;
  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const end = Math.min(
    filtered.length,
    Math.ceil((scrollTop + viewportH) / ROW_HEIGHT) + OVERSCAN
  );
  const visible = useMemo(() => filtered.slice(start, end), [filtered, start, end]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (el) setScrollTop(el.scrollTop);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    setViewportH(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  const allVisibleSelected =
    filtered.length > 0 && filtered.every((r) => selected.has(r.row_id));

  const clearFilters = () => setFilters(EMPTY_FILTERS);
  const hasFilters = Object.values(filters).some(isColumnFilterActive);

  const setCol = (key: keyof ReviewColumnFilters, next: ColumnFilterState) => {
    setFilters((f) => ({ ...f, [key]: next }));
  };

  return (
    <div className="review-table">
      <div className="review-toolbar">
        <span className="review-stats">
          {filtered.length} из {rows.length} строк
          {selected.size > 0 && ` · выбрано ${selected.size}`}
        </span>
        {hasFilters && (
          <button type="button" className="btn btn-ghost" onClick={clearFilters}>
            Сбросить фильтры
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() =>
            onToggleVisible(
              filtered.map((r) => r.row_id),
              !allVisibleSelected
            )
          }
        >
          {allVisibleSelected ? "Снять видимые" : "Выбрать видимые"}
        </button>
      </div>

      <div className="review-head">
        <div className="review-head-labels">
          <div className="review-cell review-cell--check" />
          <div className="review-cell review-cell--date">Дата</div>
          <div className="review-cell review-cell--source">Источник</div>
          <div className="review-cell review-cell--profile">Профиль</div>
          <div className="review-cell review-cell--title">Название</div>
          <div className="review-cell review-cell--brief">Краткое содержание</div>
          <div className="review-cell review-cell--stage">Стадия</div>
        </div>
        <div className="review-head-filters">
          <div className="review-cell review-cell--check" />
          <div className="review-cell review-cell--date">
            <ColumnFilter
              values={columnValues.date}
              filter={filters.date}
              onChange={(n) => setCol("date", n)}
            />
          </div>
          <div className="review-cell review-cell--source">
            <ColumnFilter
              values={columnValues.source}
              filter={filters.source}
              onChange={(n) => setCol("source", n)}
            />
          </div>
          <div className="review-cell review-cell--profile">
            <ColumnFilter
              values={columnValues.profile}
              filter={filters.profile}
              onChange={(n) => setCol("profile", n)}
            />
          </div>
          <div className="review-cell review-cell--title">
            <ColumnFilter
              values={columnValues.title}
              filter={filters.title}
              onChange={(n) => setCol("title", n)}
            />
          </div>
          <div className="review-cell review-cell--brief">
            <ColumnFilter
              values={columnValues.brief}
              filter={filters.brief}
              onChange={(n) => setCol("brief", n)}
            />
          </div>
          <div className="review-cell review-cell--stage">
            <ColumnFilter
              values={columnValues.stage}
              filter={filters.stage}
              onChange={(n) => setCol("stage", n)}
            />
          </div>
        </div>
      </div>

      <div className="review-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="review-scroll-inner" style={{ height: totalHeight }}>
          {visible.map((row, i) => {
            const index = start + i;
            return (
              <ReviewRowItem
                key={row.row_id}
                row={row}
                isSelected={selected.has(row.row_id)}
                onToggle={onToggle}
                onOpenDetail={onOpenDetail}
                style={{
                  position: "absolute",
                  top: index * ROW_HEIGHT,
                  left: 0,
                  right: 0,
                  height: ROW_HEIGHT,
                }}
              />
            );
          })}
        </div>
        {filtered.length === 0 && (
          <p className="review-empty">Нет строк по фильтрам</p>
        )}
      </div>
    </div>
  );
}
