from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rich.progress import Progress

from legal_monitor.analysis_text import (
    build_brief_changes_text,
    build_smart_fallback,
    is_bad_llm_output,
    is_stub_analysis,
    is_weak_analysis,
    resolve_adoption_status,
    sanitize_key_changes,
)
from legal_monitor.document_content import enrich_document_text, text_quality_note
from legal_monitor.config import Settings, load_profiles
from legal_monitor.llm import create_llm_client, ensure_ollama_model
from legal_monitor.models import Document, DocumentProfile, Memo, init_db
from legal_monitor.monitoring import get_monitoring_window, query_monitoring_matches
from legal_monitor.progress import start_step
from legal_monitor.utils import content_hash, extract_text_from_file

logger = logging.getLogger(__name__)

MEMO_TEMPLATE = """# Пояснительная записка

## 1. Реквизиты документа
- **Тип:** {doc_type}
- **Номер/ID:** {external_id}
- **Дата регистрации:** {register_date}
- **Источник:** {source}
- **Ссылка:** {url}
- **Стадия:** {stage}

## 2. Анализ: что принято / что изменилось
{legal_analysis}

## 3. Краткое содержание
{summary}

## 4. Ключевые изменения
{key_changes}

## 5. Практическое значение для профиля «{profile_name}»
{impact}

## 6. Риски и рекомендации
{risks}

## 7. Статус
- Релевантность: {score}
- Статус: черновик AI (требует проверки юристом)
"""


@dataclass
class DocumentAnalysis:
    summary: str
    key_changes: str
    risks: str
    legal_analysis: str = ""
    adoption_status: str = ""
    effective_date: str = ""
    impact_by_profile: dict[str, str] = field(default_factory=dict)


def run_analyze(
    settings: Settings,
    document_id: int | None = None,
    progress: Progress | None = None,
    selections: list[dict] | None = None,
) -> dict[str, int]:
    Session = init_db(str(settings.db_path))
    profiles_map = {p.id: p for p in load_profiles() if p.enabled}
    session = Session()
    stats = {
        "processed": 0,
        "memos_created": 0,
        "llm_used": 0,
        "skipped": 0,
        "skipped_cached": 0,
        "skipped_reviewed": 0,
        "shortlist_docs": 0,
    }
    llm_model = settings.llm_model
    wanted: set[tuple[int, str]] | None = None
    selection_mode = False
    if selections:
        wanted = {(int(s["document_id"]), str(s["profile_id"])) for s in selections}
        selection_mode = True

    if settings.llm_provider == "ollama":
        try:
            llm_model = ensure_ollama_model(settings)
        except Exception as exc:
            logger.error("Ollama не готова: %s", exc)

    date_from, date_to = get_monitoring_window(settings)
    step = start_step(progress, "", 0)

    try:
        query = query_monitoring_matches(session, settings)
        if document_id is not None:
            query = query.filter(Document.id == document_id)

        by_document: dict[int, list[tuple[DocumentProfile, Document]]] = defaultdict(list)
        for match, doc in query.all():
            if wanted is not None and (doc.id, match.profile_id) not in wanted:
                continue
            if match.profile_id in profiles_map:
                by_document[doc.id].append((match, doc))

        doc_order = sorted(
            by_document.keys(),
            key=lambda did: (
                by_document[did][0][1].register_date or date.min,
                max(m.relevance_score for m, _ in by_document[did]),
            ),
            reverse=True,
        )

        if wanted is not None:
            llm_budget = len(doc_order)
        elif settings.llm_all_shortlist and settings.llm_max_documents <= 0:
            llm_budget = len(doc_order)
        elif settings.llm_all_shortlist:
            llm_budget = min(len(doc_order), settings.llm_max_documents)
        else:
            llm_budget = settings.llm_max_documents

        logger.info(
            "Shortlist анализа: %s уникальных документов, LLM-бюджет=%s",
            len(doc_order),
            llm_budget if settings.llm_max_documents > 0 else "без лимита",
        )

        llm_client = None
        if _llm_available(settings):
            try:
                llm_client = create_llm_client(settings)
            except Exception as exc:
                logger.warning("LLM-клиент недоступен: %s", exc)

        step = start_step(
            progress,
            f"Анализ LLM ({date_from:%d.%m}—{date_to:%d.%m})"
            + (" · отбор" if wanted else ""),
            len(doc_order),
        )
        total = len(doc_order)

        for idx, doc_id in enumerate(doc_order, start=1):
            matches = by_document[doc_id]
            doc = matches[0][1]
            progress_label = f"Анализ LLM {idx}/{total}"

            if _document_needs_analysis(session, doc, matches, _document_hash(doc)):
                enrich_document_text(session, doc, settings)

            doc_hash = _document_hash(doc)

            if not selection_mode and not _document_needs_analysis(
                session, doc, matches, doc_hash
            ):
                stats["skipped"] += len(matches)
                stats["skipped_cached"] += len(matches)
                step.advance(1, description=f"{progress_label} (уже в БД)")
                continue

            text = _get_document_text(doc, settings.llm_text_limit)
            max_score = max(m.relevance_score for m, _ in matches)
            use_llm = _should_use_llm(
                settings, llm_client, stats, llm_budget, max_score, force=wanted is not None
            )

            analysis: DocumentAnalysis | None = None
            if use_llm:
                relevant = [(m, profiles_map[m.profile_id]) for m, _ in matches]
                logger.info(
                    "LLM [%s/%s]: «%s» (%s профилей)",
                    stats["llm_used"] + 1,
                    llm_budget if settings.llm_max_documents > 0 else len(doc_order),
                    (doc.title or "")[:60],
                    len(relevant),
                )
                analysis = _analyze_document_llm(
                    llm_client, doc, relevant, llm_model, text, settings.llm_text_limit
                )
                stats["llm_used"] += 1
            elif llm_client is None:
                logger.warning("LLM недоступен для «%s»", (doc.title or "")[:60])

            for match, doc in matches:
                profile = profiles_map[match.profile_id]
                existing_memo = (
                    session.query(Memo)
                    .filter_by(document_id=doc.id, profile_id=profile.id)
                    .one_or_none()
                )
                if (
                    not selection_mode
                    and existing_memo
                    and existing_memo.status == "reviewed"
                ):
                    stats["skipped"] += 1
                    stats["skipped_reviewed"] += 1
                    continue

                if analysis:
                    impact = analysis.impact_by_profile.get(
                        profile.id,
                        f"Документ может затрагивать «{profile.description}».",
                    )
                    summary = analysis.summary
                    key_changes = analysis.key_changes
                    risks = analysis.risks
                    legal_analysis = build_brief_changes_text(
                        key_changes,
                        resolve_adoption_status(doc.stage, analysis.adoption_status),
                        analysis.effective_date,
                    )
                else:
                    summary, key_changes, impact, risks, legal_analysis = _analyze_without_llm(
                        doc, profile, match, stats, llm_budget, llm_client is not None
                    )

                memo_md = MEMO_TEMPLATE.format(
                    doc_type=doc.doc_type or "—",
                    external_id=doc.external_id,
                    register_date=doc.register_date or "—",
                    source=doc.source,
                    url=doc.url or "—",
                    stage=doc.stage or "—",
                    legal_analysis=legal_analysis,
                    summary=summary,
                    key_changes=key_changes,
                    impact=impact,
                    risks=risks,
                    profile_name=profile.name,
                    score=match.relevance_score,
                )

                if existing_memo:
                    existing_memo.summary = summary
                    existing_memo.key_changes = key_changes
                    existing_memo.impact = impact
                    existing_memo.risks = risks
                    existing_memo.legal_analysis = legal_analysis
                    existing_memo.memo_markdown = memo_md
                    existing_memo.analyzed_hash = doc_hash
                else:
                    session.add(
                        Memo(
                            document_id=doc.id,
                            profile_id=profile.id,
                            profile_name=profile.name,
                            summary=summary,
                            key_changes=key_changes,
                            impact=impact,
                            risks=risks,
                            legal_analysis=legal_analysis,
                            memo_markdown=memo_md,
                            status="draft",
                            analyzed_hash=doc_hash,
                        )
                    )
                    stats["memos_created"] += 1
                stats["processed"] += 1

            step.advance(1, description=progress_label)

        stats["shortlist_docs"] = len(doc_order)
        session.commit()
    finally:
        step.finish()
        session.close()

    logger.info(
        "Анализ (окно %s — %s): обработано=%s, memo=%s, LLM=%s, пропущено=%s"
        " (кэш=%s, проверено вручную=%s)",
        date_from,
        date_to,
        stats["processed"],
        stats["memos_created"],
        stats["llm_used"],
        stats["skipped"],
        stats["skipped_cached"],
        stats["skipped_reviewed"],
    )
    return stats


def _should_use_llm(
    settings: Settings,
    llm_client,
    stats: dict,
    llm_budget: int,
    max_score: float,
    force: bool = False,
) -> bool:
    if llm_client is None:
        return False
    if stats["llm_used"] >= llm_budget:
        return False
    if force or settings.llm_all_shortlist:
        return True
    return max_score >= settings.llm_min_score


def _llm_available(settings: Settings) -> bool:
    if settings.llm_provider == "ollama":
        return True
    return bool(settings.llm_api_key)


def _document_hash(doc: Document) -> str:
    if doc.content_hash:
        return doc.content_hash
    return content_hash(_get_document_text(doc, limit=50000))


def _document_needs_analysis(
    session,
    doc: Document,
    matches: list[tuple[DocumentProfile, Document]],
    doc_hash: str,
) -> bool:
    for match, _ in matches:
        memo = (
            session.query(Memo)
            .filter_by(document_id=doc.id, profile_id=match.profile_id)
            .one_or_none()
        )
        if not memo:
            return True
        if memo.status == "reviewed":
            continue
        if memo.analyzed_hash != doc_hash:
            return True
        if not memo.legal_analysis:
            return True
        if is_stub_analysis(memo.legal_analysis):
            return True
        if is_stub_analysis(memo.key_changes):
            return True
        source = _get_document_text(doc, limit=50000)
        title = doc.title or ""
        if is_bad_llm_output(memo.legal_analysis, source, title):
            return True
        if is_bad_llm_output(memo.key_changes, source, title):
            return True
        if is_weak_analysis(memo.key_changes, title, source):
            return True
        if is_stub_analysis(memo.summary):
            return True
    return False


def _get_document_text(doc: Document, limit: int) -> str:
    text = (doc.text or "").strip()
    if not text and doc.files_path:
        folder = Path(doc.files_path)
        if folder.is_dir():
            parts = []
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    extracted = extract_text_from_file(path)
                    if extracted:
                        parts.append(extracted)
            text = "\n\n".join(parts).strip()
    if not text:
        text = doc.title or ""
    return text[:limit]


def _analyze_without_llm(
    doc: Document,
    profile,
    match,
    stats: dict,
    llm_budget: int,
    llm_available: bool,
) -> tuple[str, str, str, str, str]:
    if not llm_available:
        reason = "Ollama/LLM недоступна — запустите Ollama и legal-monitor ollama-setup"
    elif stats["llm_used"] >= llm_budget:
        reason = f"исчерпан лимит LLM ({llm_budget} документов за запуск)"
    else:
        reason = "LLM не вызван"

    summary = f"Документ «{doc.title}» — зона «{profile.name}»."
    key_changes = reason
    impact = f"Релевантность: {match.relevance_score}."
    risks = "Повторите анализ после запуска Ollama."
    legal_analysis = "—"
    return summary, key_changes, impact, risks, legal_analysis


def _analyze_document_llm(
    client,
    doc: Document,
    relevant: list[tuple[DocumentProfile, object]],
    llm_model: str,
    text: str,
    text_limit: int,
) -> DocumentAnalysis:
    profiles_block = "\n".join(
        f"- id={m.profile_id}, название={p.name}, описание={p.description}"
        for m, p in relevant
    )
    quality = text_quality_note(text[:text_limit], doc.title)
    prompt = f"""Ты юридический аналитик по законодательству РФ. Проанализируй нормативный документ.

Документ:
Название: {doc.title}
Тип: {doc.doc_type}
Стадия/статус: {doc.stage or 'не указана'}
Источник: {doc.source}
Текст документа:
{text[:text_limit]}

{quality}

Зоны интереса клиента:
{profiles_block}

Задача: для колонки мониторинга «Результат рассмотрения» подготовь текст в формате юридической справки.

Требования к полю key_changes (главное для отчёта):
- Начни с «Кратко:» (обязательно).
- Первый абзац — одно предложение: что именно принято, изменено, отменено или установлено
  (какой акт, поправка, постановление; не пересказ только названия).
- Далее 1–3 абзаца — КОНКРЕТНЫЕ изменения норм. Для каждого существенного изменения укажи:
  • что меняется (налог, ставка, срок, льгота, обязанность, категория лиц);
  • было → стало (цифры, проценты, суммы, сроки — если есть в тексте);
  • кому применяется;
  • статья, пункт или подпункт закона/акта (если видно в тексте).
- Если в документе несколько изменений — перечисли все значимые, не только первое.
- Если цифр в тексте нет — так и напиши («размер не указан»), но опиши суть нормы словами.
- Не выдумывай цифры и даты, которых нет в тексте документа.
- Не используй маркированные списки и строки с «- » в начале; только связные абзацы.
- Не упоминай ключевые слова, профили и зоны интереса.
- ЗАПРЕЩЕНО писать: «необходимо более подробное изучение», «требуется дополнительный анализ»,
  «документ не содержит конкретных изменений», «суть документа не раскрыта».
  Если деталей мало — напиши: «В доступном тексте детали изменений (цифры, было→стало) не указаны»
  и перечисли только то, что явно видно (статьи, субъекты, процедуры).
- Не копируй шаблоны и примеры — только факты из текста документа выше.
- ЗАПРЕЩЕНО упоминать НДФЛ, «13%», «15%», «ставку налога», если этого нет в тексте документа.
- ЗАПРЕЩЕНО использовать плейсхолдеры: «…», «(ст. …)», «с … до …», «вступают в силу с …».
- Если стадия «На рассмотрении» / «проект» / «Текст» — не пиши «приняты изменения»;
  используй «предусмотрены изменения», «на рассмотрении проект изменений».

Поле adoption_status:
- Если в блоке «Стадия/статус» выше уже указан статус из источника — используй его дословно или близко к нему.
- Если статус «не указана» — определи по тексту: опубликован / принят / на рассмотрении / проект.
- Не противоречь известному статусу из источника.

Ответь строго JSON (без markdown):
{{
  "adoption_status": "короткая фраза по стадии документа",
  "effective_date": "дата вступления в силу или «не указана»",
  "summary": "служебное: суть документа в 2-3 предложения",
  "key_changes": "Кратко:\\n\\n[первый абзац — суть]\\n\\n[второй — конкретика из текста, только проверенные факты]",
  "legal_analysis": "",
  "risks": "краткие риски для юриста (1-3 предложения)",
  "profiles": {{
    "profile_id": {{"impact": "влияние на профиль одной фразой"}}
  }}
}}
"""
    try:
        response = client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
        return _parse_document_analysis(raw, relevant, doc, text)
    except Exception as exc:
        logger.warning("LLM недоступен: %s", exc)
        return DocumentAnalysis(
            summary=f"Документ: {doc.title}",
            key_changes="LLM-анализ недоступен.",
            risks="Повторите позже или проверьте Ollama.",
            legal_analysis=build_brief_changes_text("LLM-анализ недоступен."),
        )


def _parse_document_analysis(
    raw: str,
    relevant: list[tuple[DocumentProfile, object]],
    doc: Document | None = None,
    source_text: str = "",
) -> DocumentAnalysis:
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        profiles_raw = data.get("profiles") or {}
        impact_by_profile = {}
        for match, profile in relevant:
            entry = profiles_raw.get(match.profile_id) or profiles_raw.get(profile.name) or {}
            if isinstance(entry, dict):
                impact_by_profile[match.profile_id] = str(
                    entry.get("impact", f"Затрагивает «{profile.description}».")
                )
            elif isinstance(entry, str):
                impact_by_profile[match.profile_id] = entry
        summary = str(data.get("summary", ""))
        key_changes = sanitize_key_changes(
            str(data.get("key_changes", "")),
            doc_title=doc.title if doc else "",
            doc_stage=doc.stage if doc else "",
            source_text=source_text,
        )
        if doc and is_weak_analysis(key_changes, doc.title or "", source_text):
            key_changes = build_smart_fallback(
                doc_title=doc.title or "",
                doc_stage=doc.stage,
                source_text=source_text,
            )
        adoption_status = str(data.get("adoption_status", ""))
        effective_date = str(data.get("effective_date", ""))
        resolved_status = resolve_adoption_status(
            doc.stage if doc else "", adoption_status
        )
        legal_analysis = str(data.get("legal_analysis", "")).strip()
        if not legal_analysis or legal_analysis == key_changes:
            legal_analysis = build_brief_changes_text(
                key_changes, resolved_status, effective_date
            )
        elif not legal_analysis.lower().startswith("кратко:"):
            legal_analysis = build_brief_changes_text(
                legal_analysis, resolved_status, effective_date
            )
        return DocumentAnalysis(
            summary=summary,
            key_changes=key_changes,
            risks=str(data.get("risks", "")),
            legal_analysis=legal_analysis,
            adoption_status=resolved_status or adoption_status,
            effective_date=effective_date,
            impact_by_profile=impact_by_profile,
        )
    except Exception:
        return DocumentAnalysis(
            summary=raw[:500],
            key_changes="—",
            risks="—",
            legal_analysis="—",
        )
