import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, FileItem, formatBytes, formatDate } from "../api/client";
import GlassCard from "../components/GlassCard";
import FileViewer from "../components/FileViewer";
import LoadState from "../components/LoadState";

const categoryLabel: Record<string, string> = {
  export_excel: "Excel",
  export_word: "Word (список)",
  export_selected: "Отобранные",
  download: "Скачанный",
  document_attachment: "Вложение",
};

export default function ExportsPage() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [viewerFile, setViewerFile] = useState<FileItem | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .files()
      .then((r) => setFiles(r.items.filter((f) => f.category !== "export_review")))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const id = window.setInterval(load, 15000);
    return () => window.clearInterval(id);
  }, []);

  const filtered =
    filter === "all"
      ? files.filter((f) => f.category.startsWith("export"))
      : files.filter((f) => f.category === filter || f.extension === filter);

  return (
    <>
      <h1 className="page-title">Выгрузки и файлы</h1>
      <p className="hint-dblclick">
        Двойной клик — предпросмотр. Отбор и экспорт нужных строк — в разделе{" "}
        <Link to="/documents" style={{ color: "var(--accent)" }}>
          Документы
        </Link>
      </p>

      <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[
          { id: "all", label: "Выгрузки" },
          { id: "export_excel", label: "Excel" },
          { id: "export_word", label: "Word" },
          { id: "export_selected", label: "Отобранные" },
          { id: "download", label: "Downloads" },
        ].map((f) => (
          <button
            key={f.id}
            type="button"
            className={`btn ${filter === f.id ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <LoadState loading={loading} error={error} onRetry={load} />

      {!loading && !error && (
        <GlassCard className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Тип</th>
                <th>Размер</th>
                <th>Изменён</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((f) => (
                <tr
                  key={f.id}
                  className="file-row"
                  onDoubleClick={() => setViewerFile(f)}
                  title="Двойной клик — открыть"
                >
                  <td>{f.name}</td>
                  <td>
                    <span className="badge badge-gray">
                      {categoryLabel[f.category] || f.extension.toUpperCase()}
                    </span>
                  </td>
                  <td>{formatBytes(f.size)}</td>
                  <td>{formatDate(f.modified_at)}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ color: "var(--text-secondary)" }}>
                    Нет файлов. Запустите экспорт в разделе «Конвейер».
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </GlassCard>
      )}

      <FileViewer file={viewerFile} onClose={() => setViewerFile(null)} />
    </>
  );
}
