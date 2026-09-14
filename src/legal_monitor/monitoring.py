from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Query, Session

from legal_monitor.config import Settings, get_date_window, load_profiles
from legal_monitor.models import Document, DocumentProfile


def get_monitoring_window(settings: Settings) -> tuple[date, date]:
    return get_date_window(settings)


def format_monitoring_period(settings: Settings) -> str:
    date_from, date_to = get_monitoring_window(settings)
    return f"{date_from.strftime('%d.%m')}-{date_to.strftime('%d.%m')}"


def query_monitoring_documents(session: Session, settings: Settings) -> Query:
    """Документы, опубликованные за окно мониторинга (только register_date)."""
    date_from, date_to = get_monitoring_window(settings)
    return (
        session.query(Document)
        .filter(Document.register_date.isnot(None))
        .filter(Document.register_date >= date_from)
        .filter(Document.register_date <= date_to)
        .order_by(Document.register_date.desc(), Document.id.desc())
    )


def get_monitoring_documents(session: Session, settings: Settings) -> list[Document]:
    return query_monitoring_documents(session, settings).all()


def enabled_profile_ids() -> list[str]:
    return [p.id for p in load_profiles() if p.enabled]


def query_monitoring_matches(session: Session, settings: Settings) -> Query:
    """Shortlist выгрузки: профили + опубликовано за последние N дней."""
    date_from, date_to = get_monitoring_window(settings)
    profile_ids = enabled_profile_ids()

    query = (
        session.query(DocumentProfile, Document)
        .join(Document, Document.id == DocumentProfile.document_id)
        .filter(DocumentProfile.relevance_score >= settings.relevance_threshold)
        .filter(Document.register_date.isnot(None))
        .filter(Document.register_date >= date_from)
        .filter(Document.register_date <= date_to)
    )
    if profile_ids:
        query = query.filter(DocumentProfile.profile_id.in_(profile_ids))
    else:
        query = query.filter(False)
    return query.order_by(Document.register_date.desc(), Document.id.desc())


def count_monitoring_shortlist(session: Session, settings: Settings) -> dict[str, int]:
    docs = query_monitoring_documents(session, settings).count()
    matches = query_monitoring_matches(session, settings).count()
    return {"documents": docs, "matches": matches}
