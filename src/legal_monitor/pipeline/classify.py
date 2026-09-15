from __future__ import annotations

import logging
from datetime import datetime

from rich.progress import Progress

from legal_monitor.config import Profile, Settings, load_profiles
from legal_monitor.models import Document, DocumentProfile, init_db
from legal_monitor.monitoring import get_monitoring_documents, get_monitoring_window
from legal_monitor.progress import start_step

logger = logging.getLogger(__name__)


def run_classify(settings: Settings, progress: Progress | None = None) -> dict[str, int]:
    Session = init_db(str(settings.db_path))
    profiles = [p for p in load_profiles() if p.enabled]
    session = Session()

    date_from, date_to = get_monitoring_window(settings)
    stats = {"documents": 0, "matches": 0, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()}
    step = start_step(progress, "", 0)

    try:
        documents = get_monitoring_documents(session, settings)
        stats["documents"] = len(documents)
        step = start_step(progress, f"Классификация ({date_from:%d.%m}—{date_to:%d.%m})", len(documents))

        for idx, doc in enumerate(documents, start=1):
            searchable = _build_search_text(doc)
            for profile in profiles:
                score, matched_by = score_document(searchable, profile)
                if score < settings.relevance_threshold:
                    continue

                existing = (
                    session.query(DocumentProfile)
                    .filter_by(document_id=doc.id, profile_id=profile.id)
                    .one_or_none()
                )
                if existing:
                    existing.relevance_score = score
                    existing.matched_by = matched_by
                    existing.analyzed_at = datetime.utcnow()
                else:
                    session.add(
                        DocumentProfile(
                            document_id=doc.id,
                            profile_id=profile.id,
                            profile_name=profile.name,
                            relevance_score=score,
                            matched_by=matched_by,
                        )
                    )
                stats["matches"] += 1

            step.advance(1, description=f"Классификация {idx}/{len(documents)}")

        session.commit()
    finally:
        step.finish()
        session.close()

    logger.info(
        "Классификация (окно %s — %s): документов=%s, совпадений=%s",
        date_from,
        date_to,
        stats["documents"],
        stats["matches"],
    )
    return stats


def _build_search_text(doc: Document) -> str:
    parts = [doc.title or "", doc.doc_type or "", doc.stage or "", doc.initiator or "", doc.text or ""]
    return " ".join(parts).lower()


def score_document(text: str, profile: Profile) -> tuple[float, str]:
    """Оценить релевантность документа профилю по совпадениям ключевых слов.

    Раньше формула была `min(0.95, 0.35 + (hits/len(keywords_any)) * 0.6)` -
    она опиралась на ДОЛЮ совпавших ключевых слов от общего размера списка
    профиля, а базовая константа (0.35) случайно совпадала с дефолтным
    `relevance_threshold: 0.35`. Из-за этого любой единственный хит уже
    превышал порог, независимо от размера списка ключевых слов - порог
    фактически ничего не отфильтровывал.

    Доля от размера списка вдобавок шаткая метрика для этого проекта:
    профили здесь часто содержат много однокоренных вариантов одного слова
    ("труд"/"трудов"/"трудоустрой"), и размер списка сильно различается
    между профилями (3-6 слов у одних, 20-34 у других) без прямой связи со
    специфичностью темы - одна и та же "сила" совпадения по-разному бы
    отражалась в score в зависимости от того, сколько синонимов куратор
    профиля вписал в список.

    Новая формула считает АБСОЛЮТНОЕ число различных совпавших ключевых
    слов (не долю) с убывающей отдачей: каждое следующее совпадение
    добавляет всё меньше к итоговому score, приближаясь к потолку 0.95.
    Одно случайное совпадение (например, многозначное слово вроде
    "перевод", которое есть в списках нескольких разных профилей) даёт
    ~0.30 - ниже дефолтного порога 0.35, так что больше не проходит фильтр
    автоматически. Два и более разных совпадения (что на практике часто
    случается даже для одного упоминания темы, т.к. однокоренные варианты
    в списке совпадают одновременно) дают >=0.51 - уверенно выше порога.
    """
    rules = profile.rules

    for word in rules.keywords_exclude:
        if word and word in text:
            return 0.0, "excluded"

    if not rules.keywords_any:
        return 0.0, "no_rules"

    hits = sum(1 for word in rules.keywords_any if word in text)
    if hits == 0:
        return 0.0, "no_match"

    per_hit_weight = 0.3
    score = min(0.95, 1 - (1 - per_hit_weight) ** hits)
    return round(score, 3), "keywords"
