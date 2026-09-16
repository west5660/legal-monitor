import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard } from "../api/client";
import GlassCard from "../components/GlassCard";
import LoadState from "../components/LoadState";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    api
      .dashboard()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err: Error) => {
        if (!silent) setError(err.message);
      })
      .finally(() => {
        if (!silent) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => load({ silent: true }), 15000);
    return () => clearInterval(t);
  }, [load]);

  if (loading || error || !data) {
    return (
      <>
        <h1 className="page-title">Обзор</h1>
        <LoadState loading={loading} error={error} onRetry={load} />
      </>
    );
  }

  const stats = [
    { label: "Shortlist", value: data.shortlist_documents, sub: `${data.shortlist_matches} совпадений` },
    { label: "Документов в базе", value: data.documents_total },
    { label: "Memo / анализ", value: data.memos_total },
    { label: "Выгрузок", value: data.exports_count },
  ];

  return (
    <>
      <h1 className="page-title">Обзор</h1>
      <p className="page-subtitle">
        Период мониторинга: {data.period}
        {data.job_running && " · задача выполняется…"}
      </p>

      <div className="grid-stats">
        {stats.map((s, i) => (
          <GlassCard key={s.label} className="stat-card" delay={i * 0.05}>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value">{s.value}</div>
            {s.sub && <div style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>{s.sub}</div>}
          </GlassCard>
        ))}
      </div>

      <GlassCard className="stat-card">
        <div className="stat-label">Активные профили</div>
        <p style={{ margin: "8px 0 16px", color: "var(--text-secondary)" }}>
          {data.enabled_profiles.join(", ") || "нет"}
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link to="/pipeline" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Запустить конвейер
          </Link>
          <Link to="/exports" className="btn btn-ghost" style={{ textDecoration: "none" }}>
            Открыть выгрузки
          </Link>
        </div>
      </GlassCard>
    </>
  );
}
