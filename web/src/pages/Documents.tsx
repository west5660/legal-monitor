import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, DocumentItem, FileItem, ReviewRow } from "../api/client";
import GlassCard from "../components/GlassCard";
import FileViewer from "../components/FileViewer";
import LoadState from "../components/LoadState";
import ReviewTable from "../components/ReviewTable";

function toReviewRow(d: DocumentItem): ReviewRow {
  return {
    row_id: `${d.id}:${d.profile_id}`,
    document_id: d.id,
    profile_id: d.profile_id,
    register_date: d.register_date,
    source: d.source,
    title: d.title,
    stage: d.stage || "",
    profile_name: d.profile_name,
    relevance_score: d.relevance_score,
    analysis_preview: d.analysis_preview,
    url: d.url ?? undefined,
  };
}

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [viewerFile, setViewerFile] = useState<FileItem | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [jobMsg, setJobMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .documents({ limit: 100, source: source || undefined })
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setSelected(new Set());
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [source]);

  const rows = useMemo(() => items.map(toReviewRow), [items]);

  const openDetail = useCallback(async (id: number) => {
    const d = await api.document(id);
    setDetail(d);
  }, []);

  const openAttachment = (att: FileItem) => {
    setViewerFile(att);
  };

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
    if (selected.size === 0) return;
    setExporting(true);
    setJobMsg(null);
    const selections = rows
      .filter((r) => selected.has(r.row_id))
      .map((r) => ({ document_id: r.document_id, profile_id: r.profile_id }));
    const estMin = Math.max(Math.ceil(selections.length / 2), 1);
    try {
      const job = await api.reviewExport(undefined, selections);
      setJobMsg(
        `Задача ${job.id} запущена (~${estMin} мин на ${selections.length} строк). Смотрите «Журнал».`
      );
    } catch (e) {
      setJobMsg(e instanceof Error ? e.message : "Ошибка запуска");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <h1 className="page-title">Документы</h1>
      <p className="page-subtitle">Shortlist за период мониторинга · {total} записей</p>

      <GlassCard className="stat-card review-session-bar">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 0 }}>
          <div style={{ display: "flex", gap: 8 }}>
            {["", "regulation", "sozd", "pravo"].map((s) => (
              <button
                key={s || "all"}
                type="button"
                className={`btn ${source === s ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setSource(s)}
              >
                {s || "Все"}
              </button>
            ))}
          </div>
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

      {jobMsg && (
        <p style={{ color: "var(--accent)", marginBottom: 12 }}>
          {jobMsg} <Link to="/activity">Журнал →</Link>
        </p>
      )}

      <LoadState loading={loading} error={error} onRetry={load} />

      {!loading && !error && (
        <GlassCard className="review-table-wrap">
          <ReviewTable
            rows={rows}
            selected={selected}
            onToggle={toggle}
            onToggleVisible={toggleVisible}
            onOpenDetail={openDetail}
          />
        </GlassCard>
      )}

      {detail && (
        <div className="detail-drawer glass-strong">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Карточка документа</h2>
            <button type="button" className="btn btn-ghost" onClick={() => setDetail(null)}>
              ✕
            </button>
          </div>
          <div className="detail-section">
            <h3>Название</h3>
            <p className="detail-text">{String(detail.title)}</p>
          </div>
          <div className="detail-section">
            <h3>Результат рассмотрения</h3>
            {(detail.profiles as { profile_name: string; analysis: string }[])?.map((p) => (
              <div key={p.profile_name} style={{ marginBottom: 12 }}>
                <strong>{p.profile_name}</strong>
                <p className="detail-text">{p.analysis}</p>
              </div>
            ))}
          </div>
          {(detail.attachments as FileItem[])?.length > 0 && (
            <div className="detail-section">
              <h3>Файлы</h3>
              <p className="hint-dblclick">Двойной клик — открыть файл</p>
              {(detail.attachments as FileItem[]).map((f) => (
                <div
                  key={f.id}
                  className="file-row"
                  style={{ padding: "10px 0", cursor: "pointer" }}
                  onDoubleClick={() => openAttachment(f)}
                >
                  📎 {f.name} ({Math.round(f.size / 1024)} KB)
                </div>
              ))}
            </div>
          )}
          {detail.url ? (
            <a href={String(detail.url)} target="_blank" rel="noreferrer" className="btn btn-ghost">
              Открыть на сайте источника
            </a>
          ) : null}
        </div>
      )}

      <FileViewer file={viewerFile} onClose={() => setViewerFile(null)} />
    </>
  );
}
