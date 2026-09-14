from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from rich.progress import Progress

from legal_monitor.config import Settings, get_date_window
from legal_monitor.connectors.duma import DumaApiConnector, DumaRssConnector
from legal_monitor.connectors.pravo import PravoConnector
from legal_monitor.connectors.regulation import RegulationConnector
from legal_monitor.connectors.sozd import SozdConnector
from legal_monitor.models import Document, IngestRun, RawDocument, init_db
from legal_monitor.progress import start_step
from legal_monitor.utils import content_hash, download_file, extract_text_from_file, safe_filename, _looks_like_pdf

logger = logging.getLogger(__name__)

SOURCE_LABELS: dict[str, str] = {
    "pravo": "publication.pravo.gov.ru",
    "duma_rss": "api.duma.gov.ru (RSS законопроектов)",
    "duma_api": "api.duma.gov.ru (REST API)",
    "regulation": "regulation.gov.ru",
    "sozd": "sozd.duma.gov.ru",
}


def _get_connectors(settings: Settings):
    connectors = []
    sources = settings.sources
    if sources.get("pravo", True):
        connectors.append(PravoConnector())
    if sources.get("duma_rss", True):
        connectors.append(DumaRssConnector())
    if sources.get("duma_api", False):
        connectors.append(DumaApiConnector(settings.duma_api_key))
    if sources.get("regulation", True):
        connectors.append(RegulationConnector())
    if sources.get("sozd", True):
        connectors.append(SozdConnector(use_playwright=settings.use_playwright_sozd))
    return connectors


def run_ingest(settings: Settings, progress: Progress | None = None) -> dict:
    Session = init_db(str(settings.db_path))
    date_from, date_to = get_date_window(settings)
    stats = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "errors": 0,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "sources": {},
    }

    connectors = _get_connectors(settings)
    enabled_names = [c.name for c in connectors]
    step = start_step(
        progress,
        f"Скачивание ({date_from:%d.%m}—{date_to:%d.%m})",
        len(connectors),
    )
    logger.info(
        "Скачивание документов за период %s — %s. Источники: %s",
        date_from,
        date_to,
        ", ".join(SOURCE_LABELS.get(n, n) for n in enabled_names),
    )

    for connector in connectors:
        site_label = SOURCE_LABELS.get(connector.name, connector.name)
        step.advance(0, description=f"Скачивание: {site_label}")
        source_stats = {
            "site": site_label,
            "fetched": 0,
            "new": 0,
            "updated": 0,
            "status": "ok",
            "error": None,
        }
        stats["sources"][connector.name] = source_stats

        logger.info("▶ Начало: %s (%s)", connector.name, site_label)
        run = IngestRun(source=connector.name, started_at=datetime.utcnow())
        session = Session()
        session.add(run)
        session.commit()

        try:
            raw_docs = connector.fetch(date_from, date_to)
            run.fetched_count = len(raw_docs)
            source_stats["fetched"] = len(raw_docs)
            stats["fetched"] += len(raw_docs)

            for raw in raw_docs:
                result = _save_document(session, settings, raw)
                if result == "new":
                    stats["new"] += 1
                    run.new_count += 1
                    source_stats["new"] += 1
                elif result == "updated":
                    stats["updated"] += 1
                    run.updated_count += 1
                    source_stats["updated"] += 1

            run.finished_at = datetime.utcnow()
            session.commit()
            logger.info(
                "✓ %s: найдено=%s, новых=%s, обновлено=%s",
                site_label,
                source_stats["fetched"],
                source_stats["new"],
                source_stats["updated"],
            )
        except Exception as exc:
            logger.exception("✗ Ошибка источника %s (%s): %s", connector.name, site_label, exc)
            run.error = str(exc)
            run.finished_at = datetime.utcnow()
            session.commit()
            stats["errors"] += 1
            source_stats["status"] = "error"
            source_stats["error"] = str(exc)
        finally:
            session.close()
            step.advance(1, description=f"Готово: {site_label}")

    step.finish()
    _write_ingest_report(settings, stats)

    logger.info(
        "Ingest завершён: найдено=%s, новых=%s, обновлено=%s, ошибок=%s",
        stats["fetched"],
        stats["new"],
        stats["updated"],
        stats["errors"],
    )
    for name, src in stats["sources"].items():
        status = "OK" if src["status"] == "ok" else "ОШИБКА"
        logger.info(
            "  [%s] %s — найдено=%s, новых=%s, обновлено=%s",
            status,
            src["site"],
            src["fetched"],
            src["new"],
            src["updated"],
        )
    return stats


def _write_ingest_report(settings: Settings, stats: dict) -> Path:
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "date_from": stats["date_from"],
        "date_to": stats["date_to"],
        "totals": {
            "fetched": stats["fetched"],
            "new": stats["new"],
            "updated": stats["updated"],
            "errors": stats["errors"],
        },
        "sources": stats["sources"],
    }
    path = settings.output_dir / "ingest_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Отчёт по источникам сохранён: %s", path)
    return path


def get_last_ingest_runs(settings: Settings, limit: int = 20) -> list[dict]:
    Session = init_db(str(settings.db_path))
    session = Session()
    try:
        runs = (
            session.query(IngestRun)
            .order_by(IngestRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "source": run.source,
                "site": SOURCE_LABELS.get(run.source, run.source),
                "started_at": run.started_at.isoformat() if run.started_at else "",
                "finished_at": run.finished_at.isoformat() if run.finished_at else "",
                "fetched": run.fetched_count,
                "new": run.new_count,
                "updated": run.updated_count,
                "error": run.error,
            }
            for run in runs
        ]
    finally:
        session.close()


def _save_document(session, settings: Settings, raw: RawDocument) -> str:
    existing = (
        session.query(Document)
        .filter_by(source=raw.source, external_id=raw.external_id)
        .one_or_none()
    )

    text = raw.text or ""
    files_dir = None

    if raw.file_urls:
        files_dir = _download_files(settings, raw)
        if files_dir:
            file_text = _read_downloaded_text(files_dir)
            if len(file_text) > len(text):
                text = file_text

    new_hash = content_hash(text) if text else None

    if existing:
        if new_hash and existing.content_hash != new_hash:
            existing.title = raw.title
            existing.doc_type = raw.doc_type or existing.doc_type
            existing.register_date = raw.register_date or existing.register_date
            existing.stage = raw.stage or existing.stage
            existing.url = raw.url or existing.url
            existing.initiator = raw.initiator or existing.initiator
            existing.text = text or existing.text
            existing.content_hash = new_hash
            existing.files_path = str(files_dir) if files_dir else existing.files_path
            existing.updated_at = datetime.utcnow()
            return "updated"

        updated = False
        if raw.title and len(raw.title) > len(existing.title or ""):
            existing.title = raw.title
            updated = True
        if raw.register_date and not existing.register_date:
            existing.register_date = raw.register_date
            updated = True
        elif raw.register_date and existing.register_date != raw.register_date:
            existing.register_date = raw.register_date
            updated = True
        if raw.stage and raw.stage != (existing.stage or ""):
            existing.stage = raw.stage
            updated = True
        if raw.initiator and len(raw.initiator) > len(existing.initiator or ""):
            existing.initiator = raw.initiator
            updated = True
        if text and len(text) > len(existing.text or ""):
            existing.text = text
            if new_hash:
                existing.content_hash = new_hash
            updated = True
        if files_dir and not existing.files_path:
            existing.files_path = str(files_dir)
            updated = True
        if updated:
            existing.updated_at = datetime.utcnow()
            return "updated"
        return "duplicate"

    doc = Document(
        source=raw.source,
        external_id=raw.external_id,
        title=raw.title,
        doc_type=raw.doc_type,
        register_date=raw.register_date,
        stage=raw.stage,
        url=raw.url,
        initiator=raw.initiator,
        text=text or None,
        content_hash=new_hash,
        files_path=str(files_dir) if files_dir else None,
    )
    session.add(doc)
    session.flush()
    return "new"


def _download_files(settings: Settings, raw: RawDocument) -> Path | None:
    folder = settings.downloads_dir / raw.source / safe_filename(raw.external_id)
    folder.mkdir(parents=True, exist_ok=True)
    saved = 0
    for idx, url in enumerate(raw.file_urls[:5]):
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in {".pdf", ".doc", ".docx", ".txt", ".html", ".htm"}:
            ext = ".bin"
        dest = folder / f"file_{idx}{ext}"
        if download_file(url, dest):
            if ext == ".bin" and _looks_like_pdf(dest):
                pdf_dest = dest.with_suffix(".pdf")
                dest.replace(pdf_dest)
                dest = pdf_dest
            saved += 1
    return folder if saved else None


def _read_downloaded_text(folder: Path) -> str:
    parts = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            text = extract_text_from_file(path)
            if text:
                parts.append(text)
    return "\n\n".join(parts)
