import { useEffect, useRef, useState } from "react";
import { ReviewSession } from "../api/client";

interface Props {
  sessions: ReviewSession[];
  value: string;
  onChange: (stamp: string) => void;
}

export default function SessionSelect({ sessions, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const current = sessions.find((s) => s.stamp === value);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="session-select" ref={ref}>
      <button
        type="button"
        className="session-select-trigger xlsx-filter-input"
        onClick={() => setOpen((v) => !v)}
      >
        {current
          ? `${current.period} · ${current.rows_count} строк · ${current.stamp}`
          : "— выберите выгрузку —"}
        <span className="session-select-caret">▾</span>
      </button>
      {open && (
        <ul className="session-select-menu glass-strong">
          <li>
            <button
              type="button"
              className={!value ? "active" : ""}
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
            >
              — выберите —
            </button>
          </li>
          {sessions.map((s) => (
            <li key={s.stamp}>
              <button
                type="button"
                className={s.stamp === value ? "active" : ""}
                onClick={() => {
                  onChange(s.stamp);
                  setOpen(false);
                }}
              >
                {s.period} · {s.rows_count} строк · {s.stamp}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
