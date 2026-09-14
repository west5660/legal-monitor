import { useEffect, useRef, useState } from "react";
import GlassCard from "./GlassCard";

interface Props {
  jobId: string | null;
  title?: string;
}

export default function ActivityPanel({ jobId, title = "Журнал операции" }: Props) {
  const [lines, setLines] = useState<{ ts: string; level: string; message: string }[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!jobId) {
      setLines([]);
      return;
    }

    setLines([]);
    const es = new EventSource(`/api/jobs/${jobId}/stream`);

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.level === "done" || data.level === "error") {
          es.close();
          return;
        }
        setLines((prev) => [...prev, data]);
      } catch {
        /* ignore */
      }
    };

    es.onerror = () => es.close();
    return () => es.close();
  }, [jobId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  if (!jobId) return null;

  return (
    <GlassCard className="stat-card activity-panel-wrap">
      <div className="stat-label">{title}</div>
      <div className="activity-log">
        {lines.length === 0 && (
          <div className="activity-line">Ожидание событий…</div>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`activity-line ${l.level}`}>
            [{l.ts?.slice(11, 19) || "—"}] {l.message}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </GlassCard>
  );
}
