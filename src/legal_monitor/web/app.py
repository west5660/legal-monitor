from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload

from legal_monitor.analysis_text import get_export_changes_text
from legal_monitor.config import Profile, ProfileRules, load_profiles, load_settings, save_profiles
from legal_monitor.models import Document, DocumentProfile, Memo
from legal_monitor.monitoring import (
    count_monitoring_shortlist,
    format_monitoring_period,
    get_monitoring_window,
    query_monitoring_matches,
)
from legal_monitor.pipeline.ingest import get_last_ingest_runs
from legal_monitor.pipeline.migrate_output import run_migrate_output
from legal_monitor.pipeline.review import brief_summary, list_review_sessions, load_review_rows
from legal_monitor.web.db import DB_BUSY_MESSAGE, db_session
from legal_monitor.web.files import (
    guess_media_type,
    list_document_files,
    list_files,
    resolve_file_path,
    resolve_relative_file,
)
from legal_monitor.web.jobs import JobEvent, job_manager

logger = logging.getLogger(__name__)

app = FastAPI(title="Legal Monitor", version="0.1.0")


@app.on_event("startup")
def _migrate_output_on_startup() -> None:
    try:
        settings = load_settings()
        run_migrate_output(settings)
    except Exception:
        pass


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def db_locked_handler(_request, _exc: OperationalError):
    return JSONResponse(status_code=503, content={"detail": DB_BUSY_MESSAGE})


class ProfileUpdate(BaseModel):
    enabled: Optional[bool] = None
    keywords_any: Optional[List[str]] = None


class ProfileCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    keywords_any: List[str] = Field(default_factory=list)


class JobStartRequest(BaseModel):
    stamp: Optional[str] = None
    selections: Optional[List[dict]] = None


class ReviewSelectionItem(BaseModel):
    document_id: int
    profile_id: str


class ReviewExportRequest(BaseModel):
    stamp: Optional[str] = None
    selections: List[ReviewSelectionItem]


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.exception("Unhandled API error")
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера. См. лог API."})


@app.get("/api/health")
def health() -> dict[str, Any]:
    db_ok = True
    try:
        settings = load_settings()
        with db_session(str(settings.db_path)) as session:
            session.query(Document).limit(1).count()
    except HTTPException:
        db_ok = False
    except Exception:
        logger.exception("health db check failed")
        db_ok = False
    return {"status": "ok", "job_running": job_manager.is_running, "db_ok": db_ok}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    settings = load_settings()
    with db_session(str(settings.db_path)) as session:
        docs_total = session.query(Document).count()
        matches_total = session.query(DocumentProfile).count()
        memos_total = session.query(Memo).count()
        shortlist = count_monitoring_shortlist(session, settings)
        enabled = [p.name for p in load_profiles() if p.enabled]
        date_from, date_to = get_monitoring_window(settings)

    exports = list_files(settings, include_downloads=False)
    exports = [e for e in exports if e.category.startswith("export")]
    return {
        "period": format_monitoring_period(settings),
        "date_from": str(date_from),
        "date_to": str(date_to),
        "fetch_window_days": settings.fetch_window_days,
        "documents_total": docs_total,
        "shortlist_documents": shortlist["documents"],
        "shortlist_matches": shortlist["matches"],
        "matches_total": matches_total,
        "memos_total": memos_total,
        "enabled_profiles": enabled,
        "exports_count": len(exports),
        "job_running": job_manager.is_running,
    }


@app.get("/api/documents")
def documents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    settings = load_settings()
    with db_session(str(settings.db_path)) as session:
        query = query_monitoring_matches(session, settings)
        if source:
            query = query.filter(Document.source == source)
        if profile_id:
            query = query.filter(DocumentProfile.profile_id == profile_id)

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        doc_ids = {doc.id for _, doc in rows}
        profile_ids = {match.profile_id for match, _ in rows}
        memo_map: dict[tuple[int, str], Memo] = {}
        if doc_ids and profile_ids:
            for m in (
                session.query(Memo)
                .filter(Memo.document_id.in_(doc_ids))
                .filter(Memo.profile_id.in_(profile_ids))
                .all()
            ):
                memo_map[(m.document_id, m.profile_id)] = m

        items = []
        for match, doc in rows:
            memo = memo_map.get((doc.id, match.profile_id))
            items.append(_document_row(doc, match, memo))

    return {"items": items, "total": total, "offset": offset, "limit": limit}


@app.get("/api/documents/{doc_id}")
def document_detail(doc_id: int) -> dict[str, Any]:
    settings = load_settings()
    with db_session(str(settings.db_path)) as session:
        doc = session.query(Document).filter_by(id=doc_id).one_or_none()
        if not doc:
            raise HTTPException(404, "Документ не найден")

        matches = (
            session.query(DocumentProfile)
            .filter_by(document_id=doc_id)
            .order_by(DocumentProfile.relevance_score.desc())
            .all()
        )
        memos = session.query(Memo).filter_by(document_id=doc_id).all()
        memo_by_profile = {m.profile_id: m for m in memos}

        profiles_data = []
        for match in matches:
            memo = memo_by_profile.get(match.profile_id)
            profiles_data.append(
                {
                    "profile_id": match.profile_id,
                    "profile_name": match.profile_name,
                    "relevance_score": match.relevance_score,
                    "analysis": get_export_changes_text(doc, memo, True) if memo else brief_summary(doc, None),
                    "summary": memo.summary if memo else None,
                    "risks": memo.risks if memo else None,
                    "impact": memo.impact if memo else None,
                }
            )

        attachments = list_document_files(settings, doc.files_path)
        return {
            "id": doc.id,
            "title": doc.title,
            "source": doc.source,
            "external_id": doc.external_id,
            "doc_type": doc.doc_type,
            "register_date": str(doc.register_date) if doc.register_date else None,
            "stage": doc.stage,
            "url": doc.url,
            "initiator": doc.initiator,
            "text_preview": (doc.text or "")[:4000],
            "profiles": profiles_data,
            "attachments": [a.to_dict() for a in attachments],
        }


def _document_row(doc: Document, match: DocumentProfile, memo: Memo | None) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "external_id": doc.external_id,
        "register_date": str(doc.register_date) if doc.register_date else None,
        "stage": doc.stage,
        "profile_id": match.profile_id,
        "profile_name": match.profile_name,
        "relevance_score": match.relevance_score,
        "has_memo": memo is not None,
        "analysis_preview": get_export_changes_text(doc, memo, True) if memo else brief_summary(doc, None),
        "url": doc.url,
    }


@app.get("/api/files")
def files_list(category: Optional[str] = None) -> dict[str, Any]:
    settings = load_settings()
    entries = list_files(settings)
    if category:
        entries = [e for e in entries if e.category == category or e.extension == category]
    return {"items": [e.to_dict() for e in entries]}


@app.get("/api/files/raw")
def file_raw_by_path(path: str, root: str = "output"):
    """Скачать/просмотр по относительному пути (надёжнее base64 id в URL)."""
    settings = load_settings()
    try:
        resolved = resolve_relative_file(settings, root, path)
    except FileNotFoundError:
        raise HTTPException(404, "Файл не найден")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return FileResponse(resolved, media_type=guess_media_type(resolved), filename=resolved.name)


@app.get("/api/files/{file_id}/raw")
def file_raw(file_id: str):
    settings = load_settings()
    try:
        path = resolve_file_path(settings, file_id)
    except FileNotFoundError:
        raise HTTPException(404, "Файл не найден")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return FileResponse(path, media_type=guess_media_type(path), filename=path.name)


@app.get("/api/files/{file_id}/meta")
def file_meta(file_id: str) -> dict[str, Any]:
    settings = load_settings()
    try:
        path = resolve_file_path(settings, file_id)
    except FileNotFoundError:
        raise HTTPException(404, "Файл не найден")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    stat = path.stat()
    return {
        "id": file_id,
        "name": path.name,
        "size": stat.st_size,
        "extension": path.suffix.lower().lstrip("."),
        "media_type": guess_media_type(path),
    }


@app.get("/api/ingest/history")
def ingest_history(limit: int = 20) -> dict[str, Any]:
    settings = load_settings()
    runs = get_last_ingest_runs(settings, limit=limit)
    return {"items": runs}


@app.get("/api/profiles")
def profiles_list() -> dict[str, Any]:
    items = []
    for p in load_profiles():
        items.append(
            {
                "id": p.id,
                "name": p.name,
                "enabled": p.enabled,
                "description": p.description,
                "keywords_any": p.rules.keywords_any,
                "keywords_exclude": p.rules.keywords_exclude,
            }
        )
    return {"items": items}


@app.patch("/api/profiles/{profile_id}")
def profile_update(profile_id: str, body: ProfileUpdate) -> dict[str, Any]:
    profiles = load_profiles()
    found = None
    for p in profiles:
        if p.id == profile_id:
            found = p
            if body.enabled is not None:
                p.enabled = body.enabled
            if body.keywords_any is not None:
                p.rules.keywords_any = [k.lower().strip() for k in body.keywords_any if k.strip()]
            break
    if not found:
        raise HTTPException(404, "Профиль не найден")
    save_profiles(profiles)
    return {"ok": True}


@app.post("/api/profiles")
def profile_create(body: ProfileCreate) -> dict[str, Any]:
    profiles = load_profiles()
    if any(p.id == body.id for p in profiles):
        raise HTTPException(400, "Профиль с таким ID уже существует")
    profiles.append(
        Profile(
            id=body.id,
            name=body.name,
            enabled=True,
            description=body.description,
            rules=ProfileRules(
                keywords_any=[k.lower().strip() for k in body.keywords_any if k.strip()],
                keywords_exclude=[],
            ),
        )
    )
    save_profiles(profiles)
    return {"ok": True}


@app.get("/api/review/sessions")
def review_sessions(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    settings = load_settings()
    items = list_review_sessions(settings, limit=limit)
    return {"items": items}


@app.get("/api/review/{stamp}/rows")
def review_rows(stamp: str) -> dict[str, Any]:
    settings = load_settings()
    data = load_review_rows(settings, stamp)
    if not data:
        raise HTTPException(404, "Сессия отбора не найдена. Сначала выполните экспорт списка.")
    return data


@app.post("/api/review/export")
def review_export(body: ReviewExportRequest) -> dict[str, Any]:
    if not body.selections:
        raise HTTPException(400, "Выберите хотя бы одну строку")
    try:
        job = job_manager.start_job(
            "review_export",
            stamp=body.stamp,
            selections=[s.model_dump() for s in body.selections],
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return job.to_dict()


@app.get("/api/jobs")
def jobs_list(limit: int = 30) -> dict[str, Any]:
    jobs = job_manager.list_jobs(limit=limit)
    return {"items": [j.to_dict() for j in jobs], "running": job_manager.is_running}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict[str, Any]:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job.to_dict()


@app.post("/api/jobs/{job_type}")
def job_start(job_type: str, body: Optional[JobStartRequest] = None) -> dict[str, Any]:
    allowed = {
        "ingest",
        "classify",
        "export_flow",
        "full",
        "cleanup",
        "review_export",
    }
    if job_type not in allowed:
        raise HTTPException(400, f"Неизвестный тип: {job_type}")
    kwargs: dict[str, Any] = {}
    if body:
        if body.stamp:
            kwargs["stamp"] = body.stamp
        if body.selections:
            kwargs["selections"] = body.selections
    try:
        job = job_manager.start_job(job_type, **kwargs)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return job.to_dict()


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")

    queue: asyncio.Queue[JobEvent | None] = asyncio.Queue()

    def on_event(event: JobEvent) -> None:
        queue.put_nowait(event)

    job_manager.subscribe(job_id, on_event)

    async def generate():
        try:
            for event in job.events:
                yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
            while True:
                if job.status.value in ("done", "error") and queue.empty():
                    payload = {
                        "ts": "",
                        "level": "done" if job.status.value == "done" else "error",
                        "message": job.error or "completed",
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if event:
                        yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            job_manager.unsubscribe(job_id, on_event)

    return StreamingResponse(generate(), media_type="text/event-stream")


def create_app() -> FastAPI:
    return app
