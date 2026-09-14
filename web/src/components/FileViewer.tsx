import { useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import * as XLSX from "xlsx";
import { motion, AnimatePresence } from "framer-motion";
import { api, FileItem } from "../api/client";
import ExcelViewer from "./ExcelViewer";

interface Props {
  file: FileItem | null;
  onClose: () => void;
}

export default function FileViewer({ file, onClose }: Props) {
  const docxRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [xlsxRows, setXlsxRows] = useState<string[][]>([]);
  const [xlsxHeaders, setXlsxHeaders] = useState<string[]>([]);
  const [xlsxTruncated, setXlsxTruncated] = useState(false);

  const ext = file?.extension?.toLowerCase() ?? "";
  const rawUrl = file ? api.fileRawUrl(file) : "";

  useEffect(() => {
    if (!file) return;

    setError(null);
    setXlsxRows([]);
    setXlsxHeaders([]);
    setXlsxTruncated(false);
    setLoading(true);

    const load = async () => {
      try {
        const res = await fetch(rawUrl);
        if (!res.ok) {
          let msg = `Файл недоступен (${res.status})`;
          try {
            const body = await res.json();
            if (typeof body.detail === "string") msg = body.detail;
          } catch {
            /* not json */
          }
          throw new Error(msg);
        }
        const buf = await res.arrayBuffer();
        if (buf.byteLength < 64) {
          throw new Error("Файл пустой или повреждён");
        }
        if (ext === "docx" && docxRef.current) {
          docxRef.current.innerHTML = "";
          await renderAsync(buf, docxRef.current, undefined, {
            className: "docx-preview-inner",
            inWrapper: true,
          });
        } else if (ext === "xlsx") {
          const wb = XLSX.read(buf, { type: "array" });
          const sheet = wb.Sheets[wb.SheetNames[0]];
          const data = XLSX.utils.sheet_to_json<string[]>(sheet, {
            header: 1,
            defval: "",
          }) as string[][];
          if (data.length) {
            const maxRows = 500;
            const body = data.slice(1);
            setXlsxHeaders((data[0] ?? []).map(String));
            setXlsxRows(body.slice(0, maxRows).map((r) => r.map(String)));
            setXlsxTruncated(body.length > maxRows);
          } else {
            throw new Error("Excel-лист пустой");
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [file, ext, rawUrl]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <AnimatePresence>
      {file && (
        <motion.div
          className="viewer-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            className={`viewer-panel glass-strong${ext === "xlsx" ? " viewer-panel--wide" : ""}`}
            initial={{ scale: 0.96, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.96, opacity: 0 }}
          >
            <div className="viewer-header">
              <span className="viewer-title">{file.name}</span>
              <div style={{ display: "flex", gap: 8 }}>
                <a
                  className="btn btn-ghost"
                  href={rawUrl}
                  download={file.name}
                  style={{ textDecoration: "none" }}
                >
                  Скачать
                </a>
                <button type="button" className="btn btn-ghost" onClick={onClose}>
                  Закрыть
                </button>
              </div>
            </div>
            <div className={`viewer-body${ext === "xlsx" ? " viewer-body--xlsx" : ""}`}>
              {loading && <p style={{ color: "var(--text-secondary)" }}>Загрузка…</p>}
              {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

              {ext === "pdf" && !loading && (
                <iframe title={file.name} src={rawUrl} />
              )}

              {(ext === "docx" || ext === "doc") && (
                <div ref={docxRef} className="docx-container" />
              )}

              {ext === "xlsx" && !loading && !error && xlsxHeaders.length === 0 && (
                <p className="detail-text">Не удалось прочитать таблицу Excel.</p>
              )}

              {ext === "xlsx" && !loading && !error && xlsxHeaders.length > 0 && (
                <ExcelViewer
                  key={file.id}
                  headers={xlsxHeaders}
                  rows={xlsxRows}
                  truncated={xlsxTruncated}
                />
              )}

              {ext === "bin" && (
                <p className="detail-text">
                  Бинарный файл. Попробуйте скачать — возможно, это PDF под другим расширением.
                </p>
              )}

              {!["pdf", "docx", "doc", "xlsx", "bin"].includes(ext) && !loading && (
                <p className="detail-text">
                  Предпросмотр недоступен.{" "}
                  <a href={rawUrl} download={file.name}>
                    Скачать файл
                  </a>
                </p>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
