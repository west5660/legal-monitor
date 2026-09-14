import { useEffect, useState } from "react";
import { api, DocumentItem, FileItem } from "../api/client";
import GlassCard from "../components/GlassCard";
import FileViewer from "../components/FileViewer";
import LoadState from "../components/LoadState";

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [viewerFile, setViewerFile] = useState<FileItem | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .documents({ limit: 100, source: source || undefined })
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [source]);

  const openDetail = async (id: number) => {
    const d = await api.document(id);
    setDetail(d);
  };

  const openAttachment = (att: FileItem) => {
    setViewerFile(att);
  };

  return (
    <>
      <h1 className="page-title">Документы</h1>
      <p className="page-subtitle">Shortlist за период мониторинга · {total} записей</p>

      <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
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

      <LoadState loading={loading} error={error} onRetry={load} />

      {!loading && !error && (
      <GlassCard className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Дата</th>
              <th>Источник</th>
              <th>Профиль</th>
              <th>Название</th>
              <th>Анализ</th>
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr
                key={`${d.id}-${d.profile_name}`}
                className="file-row"
                onDoubleClick={() => openDetail(d.id)}
                title="Двойной клик — карточка документа"
              >
                <td>{d.register_date ?? "—"}</td>
                <td>
                  <span className="badge badge-blue">{d.source}</span>
                </td>
                <td>{d.profile_name}</td>
                <td style={{ maxWidth: 320 }}>{d.title}</td>
                <td style={{ maxWidth: 280, fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                  {(d.analysis_preview || "—").slice(0, 120)}
                  {(d.analysis_preview?.length ?? 0) > 120 ? "…" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
