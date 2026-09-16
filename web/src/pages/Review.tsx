import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ReviewData, ReviewSession } from "../api/client";
import GlassCard from "../components/GlassCard";
import LoadState from "../components/LoadState";
import ReviewTable from "../components/ReviewTable";
import SessionSelect from "../components/SessionSelect";

export default function ReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState<ReviewSession[]>([]);
  const [data, setData] = useState<ReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [jobMsg, setJobMsg] = useState<string | null>(null);

  const stamp = searchParams.get("stamp") || sessions[0]?.stamp || "";

  const loadSessions = useCallback(() => {
    api.reviewSessions().then((r) => setSessions(r.items)).catch(() => {});
  }, []);

  const loadRows = useCallback((s: string) => {
    if (!s) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .reviewRows(s)
      .then((d) => {
        setData(d);
        setSelected(new Set());
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (stamp) loadRows(stamp);
  }, [stamp, loadRows]);

  const toggle = useCallback((rowId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });
  }, []);

  const toggleVisible = useCallback((rowIds: string[], select: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of rowIds) {
        if (select) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  const runExport = async () => {
    if (!data || selected.size === 0) return;
    setExporting(true);
    setJobMsg(null);
    const selections = data.rows
      .filter((r) => selected.has(r.row_id))
      .map((r) => ({ document_id: r.document_id, profile_id: r.profile_id }));
    const estMin = Math.max(Math.ceil(selections.length / 2), 1);
    try {
      const job = await api.reviewExport(data.stamp, selections);
      setJobMsg(
        `Задача ${job.id} запущена (~${estMin} мин на ${selections.length} строк). Смотрите «Журнал».`
      );
    } catch (e) {
      setJobMsg(e instanceof Error ? e.message : "Ошибка запуска");
    } finally {
      setExporting(false);
    }
  };

  const onStampChange = (s: string) => {
    setSearchParams(s ? { stamp: s } : {});
  };

  return (
    <>
      <h1 className="page-title">Аналитический отбор</h1>
      <p className="page-subtitle">
        Фильтры в заголовках столбцов · отметьте строки · экспорт выбранных → Word в{" "}
        <code>output/selected/</code>
      </p>

      <GlassCard className="stat-card review-session-bar">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 0 }}>
          <label className="review-session-label">
            Выгрузка:{" "}
            <SessionSelect sessions={sessions} value={stamp} onChange={onStampChange} />
          </label>
          {data && (
            <span style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
              Период {data.period} · {data.rows.length} строк
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={selected.size === 0 || exporting}
            onClick={runExport}
            style={{ marginLeft: "auto" }}
          >
            {exporting ? "Запуск…" : `Экспорт выбранного (${selected.size})`}
          </button>
        </div>
      </GlassCard>

      {!stamp && !loading && (
        <p className="page-subtitle">
          Нет данных для отбора. Выполните «Экспорт списка» в конвейере, затем вернитесь сюда.
        </p>
      )}

      {jobMsg && (
        <p style={{ color: "var(--accent)", marginBottom: 12 }}>
          {jobMsg} <Link to="/activity">Журнал →</Link>
        </p>
      )}

      <LoadState loading={loading} error={error} onRetry={() => loadRows(stamp)} />

      {!loading && !error && data && (
        <GlassCard className="review-table-wrap">
          <ReviewTable
            rows={data.rows}
            selected={selected}
            onToggle={toggle}
            onToggleVisible={toggleVisible}
          />
        </GlassCard>
      )}
    </>
  );
}
