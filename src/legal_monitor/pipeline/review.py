from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from legal_monitor.analysis_text import get_export_changes_text
from legal_monitor.config import Settings
from legal_monitor.models import Document, DocumentProfile, Memo
from legal_monitor.monitoring import format_monitoring_period
from legal_monitor.pipeline.output_dirs import output_dirs


def rows_to_review_payload(
    settings: Settings,
    stamp: str,
    rows: list[tuple[Document, Memo | None, DocumentProfile]],
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for doc, memo, match in rows:
        items.append(
            {
                "row_id": f"{doc.id}:{match.profile_id}",
                "document_id": doc.id,
                "profile_id": match.profile_id,
                "register_date": str(doc.register_date) if doc.register_date else None,
                "source": doc.source,
                "doc_type": doc.doc_type or "",
                "external_id": doc.external_id,
                "title": doc.title,
                "stage": doc.stage or "",
                "url": doc.url or "",
                "profile_name": match.profile_name,
                "relevance_score": match.relevance_score,
                "analysis_preview": get_export_changes_text(doc, memo, bool(memo)),
                "brief_summary": _brief_summary(doc, memo),
            }
        )
    return {
        "stamp": stamp,
        "period": format_monitoring_period(settings),
        "date_from": str(date_from),
        "date_to": str(date_to),
        "rows": items,
    }


def save_review_bundle(
    settings: Settings,
    payload: dict[str, Any],
) -> tuple[Path, Path | None]:
    dirs = output_dirs(settings)
    stamp = payload["stamp"]
    json_path = dirs["review"] / f"{stamp}_rows.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path, None


def _brief_summary(doc: Document, memo: Memo | None) -> str:
    if memo and memo.summary and memo.summary.strip() not in ("—", "-"):
        text = memo.summary.strip()
    elif doc.text and doc.text.strip():
        text = " ".join(doc.text.split())
    elif doc.title and doc.title.strip():
        text = doc.title.strip()
    else:
        parts = [p for p in (doc.doc_type, doc.stage, doc.initiator) if p]
        text = " · ".join(parts) if parts else ""
    if not text:
        return "—"
    return text[:500] + ("…" if len(text) > 500 else "")


def _meaningful_summary(value: str | None) -> bool:
    if not value:
        return False
    return value.strip() not in ("—", "-", "")


def _ensure_brief_summaries(data: dict[str, Any]) -> None:
    for row in data.get("rows", []):
        if _meaningful_summary(row.get("brief_summary")):
            continue
        preview = row.get("analysis_preview") or ""
        if _meaningful_summary(preview):
            row["brief_summary"] = preview.strip()
            continue
        title = (row.get("title") or "").strip()
        stage = (row.get("stage") or "").strip()
        if title and stage:
            row["brief_summary"] = f"{title[:280]} ({stage})"
        elif title:
            row["brief_summary"] = title[:320]
        elif stage:
            row["brief_summary"] = stage
        else:
            row["brief_summary"] = "—"


def load_review_rows(settings: Settings, stamp: str) -> dict[str, Any] | None:
    dirs = output_dirs(settings)
    for base in (dirs["review"], dirs["root"]):
        path = base / f"{stamp}_rows.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            _ensure_brief_summaries(data)
            return data
    return None


def list_review_sessions(settings: Settings, limit: int = 30) -> list[dict[str, Any]]:
    dirs = output_dirs(settings)
    seen: set[str] = set()
    sessions: list[dict[str, Any]] = []
    paths: list[Path] = []
    for base in (dirs["review"], dirs["root"]):
        if base.is_dir():
            paths.extend(base.glob("*_rows.json"))
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session_stamp = data.get("stamp", path.stem.replace("_rows", ""))
            if session_stamp in seen:
                continue
            seen.add(session_stamp)
            sessions.append(
                {
                    "stamp": session_stamp,
                    "period": data.get("period", ""),
                    "rows_count": len(data.get("rows", [])),
                    "modified_at": path.stat().st_mtime,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
        if len(sessions) >= limit:
            break
    return sessions

