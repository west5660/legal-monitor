import { useEffect, useState } from "react";
import { api } from "../api/client";
import GlassCard from "../components/GlassCard";
import ActivityPanel from "../components/ActivityPanel";

export default function PipelinePage() {
  const [running, setRunning] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.jobs().then((j) => setRunning(j.running));
  }, [activeJobId]);

  const start = async (type: string, withAnalysis = false) => {
    setError(null);
    try {
      const job = await api.startJob(type, withAnalysis);
      setActiveJobId(job.id);
      setRunning(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка запуска");
    }
  };

  return (
    <>
      <h1 className="page-title">Конвейер</h1>
      <p className="page-subtitle">
        Скачивание → классификация → экспорт списка → отбор строк → LLM по выбранным. Одна задача за раз.
      </p>

      {error && (
        <p style={{ color: "var(--danger)", marginBottom: 16 }}>{error}</p>
      )}

      <div className="pipeline-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={running}
          onClick={() => start("full", false)}
        >
          Полный цикл
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={running}
          onClick={() => start("full", true)}
        >
          Полный цикл + LLM
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("ingest")}>
          Скачать
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("classify")}>
          Классифицировать
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("analyze")}>
          LLM-анализ
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("export_flow", false)}>
          Экспорт (список)
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("export_flow", true)}>
          Экспорт + анализ
        </button>
        <button type="button" className="btn btn-ghost" disabled={running} onClick={() => start("cleanup")}>
          Очистка
        </button>
      </div>

      <GlassCard className="stat-card">
        <div className="stat-label">Статус</div>
        <p>{running ? "Выполняется задача…" : "Готов к запуску"}</p>
      </GlassCard>

      <ActivityPanel jobId={activeJobId} />
    </>
  );
}
