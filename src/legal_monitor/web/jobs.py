from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from legal_monitor.config import Settings, load_settings
from legal_monitor.pipeline.analyze import run_analyze
from legal_monitor.pipeline.classify import run_classify
from legal_monitor.pipeline.export import run_cleanup, run_export, run_export_flow, run_export_selected
from legal_monitor.pipeline.ingest import run_ingest
from legal_monitor.progress import create_progress


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class JobEvent:
    ts: str
    level: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"ts": self.ts, "level": self.level, "message": self.message}


@dataclass
class Job:
    id: str
    job_type: str
    status: JobStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.job_type,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "events": [e.to_dict() for e in self.events],
        }


class JobLogHandler(logging.Handler):
    def __init__(self, emit_fn: Callable[[str, str], None]) -> None:
        super().__init__()
        self._emit_fn = emit_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._emit_fn(record.levelname.lower(), msg)
        except Exception:
            pass


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._running = False
        self._subscribers: dict[str, list[Callable[[JobEvent], None]]] = {}

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def subscribe(self, job_id: str, callback: Callable[[JobEvent], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(callback)

    def unsubscribe(self, job_id: str, callback: Callable[[JobEvent], None]) -> None:
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            if callback in subs:
                subs.remove(callback)

    def _emit(self, job: Job, level: str, message: str) -> None:
        event = JobEvent(
            ts=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            level=level,
            message=message,
        )
        with self._lock:
            job.events.append(event)
            if len(job.events) > 500:
                job.events = job.events[-500:]
            subs = list(self._subscribers.get(job.id, []))
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass

    def start_job(self, job_type: str, **kwargs: Any) -> Job:
        with self._lock:
            if self._running:
                raise RuntimeError("Уже выполняется другая задача. Дождитесь завершения.")
            self._running = True

        job = Job(
            id=str(uuid.uuid4())[:8],
            job_type=job_type,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )
        with self._lock:
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job, kwargs),
            daemon=True,
        )
        thread.start()
        return job

    def _run_job(self, job: Job, kwargs: dict[str, Any]) -> None:
        settings = load_settings()
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._emit(job, "info", f"Запуск: {job.job_type}")

        handler = JobLogHandler(lambda level, msg: self._emit(job, level, msg))
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)

        try:
            result = self._execute(job.job_type, settings, kwargs)
            job.result = result
            job.status = JobStatus.DONE
            self._emit(job, "info", "Готово.")
        except Exception as exc:
            job.status = JobStatus.ERROR
            job.error = str(exc)
            self._emit(job, "error", str(exc))
        finally:
            job.finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            root.removeHandler(handler)
            with self._lock:
                self._running = False

    def _execute(self, job_type: str, settings: Settings, kwargs: dict[str, Any]) -> dict[str, Any]:
        with_analysis = bool(kwargs.get("with_analysis", False))

        if job_type == "ingest":
            with create_progress() as progress:
                stats = run_ingest(settings, progress=progress)
            return stats

        if job_type == "classify":
            with create_progress() as progress:
                stats = run_classify(settings, progress=progress)
            return stats

        if job_type == "analyze":
            with create_progress() as progress:
                stats = run_analyze(settings, progress=progress)
            return stats

        if job_type == "export":
            paths = run_export(settings, with_analysis=with_analysis)
            return {
                "excel": str(paths.excel),
                "word": str(paths.word),
                "rows": paths.rows,
            }

        if job_type == "export_flow":
            result = run_export_flow(
                settings,
                progress=None,
                ask_analyze=False,
                run_analysis=with_analysis,
            )
            out: dict[str, Any] = {
                "list_excel": str(result.list_export.excel),
                "list_word": str(result.list_export.word),
            }
            if result.analysis_export:
                out["analysis_excel"] = str(result.analysis_export.excel)
                out["analysis_word"] = str(result.analysis_export.word)
            return out

        if job_type == "full":
            with create_progress() as progress:
                ingest_stats = run_ingest(settings, progress=progress)
                run_classify(settings, progress=progress)
            if with_analysis:
                with create_progress() as progress:
                    flow = run_export_flow(
                        settings,
                        progress=progress,
                        ask_analyze=False,
                        run_analysis=True,
                    )
            else:
                flow = run_export_flow(
                    settings,
                    progress=None,
                    ask_analyze=False,
                    run_analysis=False,
                )
            return {"ingest": ingest_stats, "export": self._flow_paths(flow)}

        if job_type == "cleanup":
            return run_cleanup(settings)

        if job_type == "review_analyze":
            selections = kwargs.get("selections") or []
            stamp = kwargs.get("stamp")
            with create_progress() as progress:
                analyze_stats = run_analyze(
                    settings, progress=progress, selections=selections
                )
                export_paths = run_export_selected(
                    settings, selections, stamp=stamp, progress=progress
                )
            return {
                "analyze": analyze_stats,
                "word": str(export_paths.word),
                "rows": export_paths.rows,
                "stamp": export_paths.stamp,
            }

        raise ValueError(f"Неизвестный тип задачи: {job_type}")

    @staticmethod
    def _flow_paths(flow) -> dict[str, str]:
        out = {
            "list_excel": str(flow.list_export.excel),
            "list_word": str(flow.list_export.word),
        }
        if flow.analysis_export:
            out["analysis_excel"] = str(flow.analysis_export.excel)
            out["analysis_word"] = str(flow.analysis_export.word)
        return out

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running


job_manager = JobManager()
