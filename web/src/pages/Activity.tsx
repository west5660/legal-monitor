import { useEffect, useState } from "react";
import { api, Job, formatDate } from "../api/client";
import GlassCard from "../components/GlassCard";

export default function ActivityPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [ingest, setIngest] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    api.jobs().then((r) => setJobs(r.items)).catch(console.error);
    api.ingestHistory().then((r) => setIngest(r.items)).catch(console.error);
  }, []);

  const openJob = async (id: string) => {
    const j = await api.job(id);
    setSelected(j);
  };

  return (
    <>
      <h1 className="page-title">Журнал</h1>
      <p className="page-subtitle">История задач и скачиваний</p>

      <h2 style={{ fontSize: "1rem", marginBottom: 12 }}>Задачи</h2>
      <GlassCard className="table-wrap activity-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Тип</th>
              <th>Статус</th>
              <th>Создана</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr
                key={j.id}
                className="file-row"
                onDoubleClick={() => openJob(j.id)}
                title="Двойной клик — детали"
              >
                <td>{j.id}</td>
                <td>{j.type}</td>
                <td>
                  <span
                    className={`badge ${
                      j.status === "done" ? "badge-green" : j.status === "error" ? "badge-gray" : "badge-blue"
                    }`}
                  >
                    {j.status}
                  </span>
                </td>
                <td>{formatDate(j.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      {selected && (
        <GlassCard className="stat-card">
          <div className="stat-label">
            Задача {selected.id} · {selected.type}
          </div>
          {selected.error && <p style={{ color: "var(--danger)" }}>{selected.error}</p>}
          <div className="activity-log" style={{ maxHeight: 400 }}>
            {selected.events.map((e, i) => (
              <div key={i} className={`activity-line ${e.level}`}>
                [{e.ts?.slice(11, 19)}] {e.message}
              </div>
            ))}
          </div>
          <button type="button" className="btn btn-ghost" style={{ marginTop: 12 }} onClick={() => setSelected(null)}>
            Закрыть
          </button>
        </GlassCard>
      )}

      <h2 style={{ fontSize: "1rem", margin: "28px 0 12px" }}>Скачивания по источникам</h2>
      <GlassCard className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Время</th>
              <th>Источник</th>
              <th>Найдено</th>
              <th>Новых</th>
            </tr>
          </thead>
          <tbody>
            {ingest.map((r, i) => (
              <tr key={i}>
                <td>{String(r.started_at ?? "").slice(0, 19)}</td>
                <td>{String(r.source)}</td>
                <td>{String(r.fetched)}</td>
                <td>{String(r.new)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  );
}
