from __future__ import annotations

import re

from legal_monitor.models import Document, Memo

HEDGE_PHRASES = (
    "необходимо более подробное изучение",
    "необходимость более подробного изучения",
    "требуется дополнительный анализ",
    "требуется более подробное",
    "документ не содержит конкретных изменений",
    "суть документа не раскрыта",
    "для определения конкретных изменений",
    "не указаны цифры или другие детали",
    "не указаны цифры или иные детали",
    "конкретные изменения (например, ставки налогов",
    "не указаны в данном документе",
    "не указаны в тексте",
)

PROMPT_ARTIFACT_PHRASES = (
    "13% до 15%",
    "13% до 15",
    "с 13% до 15",
    "ставка налога повышена",
    "повышена с 13%",
    "ставка налога не изменена",
    "приняты изменения в …",
    "изменения в …",
)

PLACEHOLDER_MARKERS = (
    "(ст. …)",
    "ст. …",
    "(ст …)",
    "с … до",
    "вступают в силу с …",
    "в силу с …",
    "размер не указан (ст",
)

STUB_MARKERS = (
    "Автоматический режим без LLM",
    "Совпали ключевые слова:",
    "LLM-анализ не выполнен",
    "Ollama/LLM недоступна",
    "ГЛАВНОЕ:",
    *HEDGE_PHRASES,
    *PROMPT_ARTIFACT_PHRASES,
)

_GARBAGE_STAGES = frozenset({"текст", "text", "—", "-", ""})
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WORDS = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def is_stub_analysis(text: str | None) -> bool:
    if not text or not text.strip():
        return True
    low = text.lower()
    if low in ("—", "-", "кратко:", "кратко:\n—", "кратко:\n\n—"):
        return True
    return any(marker.lower() in low for marker in STUB_MARKERS)


def contains_prompt_artifact(text: str, source_text: str = "") -> bool:
    """Фразы из старого промпта/примеров, которых нет в исходном тексте."""
    body = (text or "").lower()
    source = (source_text or "").lower()
    for phrase in PROMPT_ARTIFACT_PHRASES:
        if phrase in body and phrase not in source:
            return True
    if "13%" in body and "15%" in body and "13% до 15" not in source and "15%" not in source:
        if any(w in body for w in ("налог", "ндфл", "ставк")):
            return True
    return False


def contains_placeholder_garbage(text: str) -> bool:
    low = (text or "").lower()
    return any(marker.lower() in low for marker in PLACEHOLDER_MARKERS)


def is_bad_llm_output(
    text: str | None,
    source_text: str = "",
    title: str = "",
) -> bool:
    return (
        is_stub_analysis(text)
        or contains_prompt_artifact(text, source_text)
        or contains_placeholder_garbage(text)
        or is_title_paraphrase(text or "", title)
        or is_weak_analysis(text, title, source_text)
    )


def _normalize_compare(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _word_overlap(a: str, b: str) -> float:
    wa = set(_WORDS.findall(_normalize_compare(a)))
    wb = set(_WORDS.findall(_normalize_compare(b)))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _body_after_kratko(text: str) -> str:
    body = (text or "").strip()
    if body.lower().startswith("кратко:"):
        return body[7:].strip()
    return body


def is_title_paraphrase(changes: str, title: str) -> bool:
    """True, если текст — почти дословный пересказ названия без новой информации."""
    body = _body_after_kratko(changes)
    if not body or not title:
        return False
    paragraphs = [
        p.strip()
        for p in body.split("\n\n")
        if p.strip()
        and not p.strip().lower().startswith("статус:")
        and not p.strip().lower().startswith("вступление в силу:")
    ]
    if not paragraphs:
        return True
    if len(paragraphs) >= 2:
        tail = paragraphs[-1].lower()
        if tail.startswith("в доступном тексте детали"):
            return False
        if _word_overlap(paragraphs[-1], title) < 0.65 and len(paragraphs[-1]) > 55:
            return False
    content = paragraphs[0]
    if _normalize_compare(content) in _normalize_compare(title):
        return True
    overlap = _word_overlap(content, title)
    if overlap >= 0.82:
        extra_digits = set(re.findall(r"\d+", content)) - set(re.findall(r"\d+", title))
        if not extra_digits and len(content) < len(title) * 1.15:
            return True
    return False


def is_weak_analysis(text: str | None, title: str = "", source_text: str = "") -> bool:
    if not text or is_stub_analysis(text):
        return True
    if contains_prompt_artifact(text, source_text) or contains_placeholder_garbage(text):
        return True
    if is_title_paraphrase(text, title):
        return True
    body = _body_after_kratko(text)
    if len(body) < 40:
        return True
    if body.strip() in ("—", "-"):
        return True
    return False


def _is_pending_stage(stage: str | None) -> bool:
    value = (stage or "").lower()
    return any(
        token in value
        for token in ("на рассмотрении", "проект", "текст", "уведомлен")
    )


def _sentence_has_issue(sentence: str, source_text: str) -> bool:
    low = sentence.lower()
    if any(h in low for h in HEDGE_PHRASES):
        return True
    if contains_prompt_artifact(sentence, source_text):
        return True
    if contains_placeholder_garbage(sentence):
        return True
    return False


def _split_sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def _clean_paragraph(paragraph: str, source_text: str) -> str:
    sentences = _split_sentences(paragraph)
    clean = [s for s in sentences if not _sentence_has_issue(s, source_text)]
    return " ".join(clean).strip()


def _fix_pending_wording(text: str, stage: str | None) -> str:
    if not _is_pending_stage(stage):
        return text
    replacements = (
        ("Приняты изменения", "Предусмотрены изменения"),
        ("приняты изменения", "предусмотрены изменения"),
        ("Принят ", "На рассмотрении проект: "),
        ("Установлен ", "Предусматривается установление "),
        ("Установлено ", "Предусматривается установление "),
    )
    result = text
    for old, new in replacements:
        if old in result:
            result = result.replace(old, new, 1)
            break
    return result


def _short_title(title: str, max_len: int = 180) -> str:
    value = re.sub(r"\s+", " ", (title or "").strip())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def _extract_source_excerpt(source_text: str, title: str, max_len: int = 320) -> str:
    source = re.sub(r"\s+", " ", (source_text or "").strip())
    title_norm = _normalize_compare(title)
    if not source or _normalize_compare(source) == title_norm:
        return ""
    if source.startswith(title[: min(len(title), 80)]):
        source = source[len(title) :].strip(" .—–-")
    sentences = _split_sentences(source[:8000])
    picked: list[str] = []
    length = 0
    for sentence in sentences:
        if len(sentence) < 35:
            continue
        if _word_overlap(sentence, title) > 0.9:
            continue
        if _sentence_has_issue(sentence, source_text):
            continue
        picked.append(sentence)
        length += len(sentence)
        if length >= max_len:
            break
    return " ".join(picked)[:max_len].strip()


def build_smart_fallback(
    *,
    doc_title: str = "",
    doc_stage: str | None = None,
    source_text: str = "",
) -> str:
    title = _short_title(doc_title)
    excerpt = _extract_source_excerpt(source_text, doc_title)
    if _is_pending_stage(doc_stage):
        lead = f"На рассмотрении проект: {title}."
    else:
        lead = f"Документ: {title}."
    if excerpt:
        detail = excerpt
    else:
        detail = "В доступном тексте детали изменений (цифры, было→стало) не указаны."
    return f"Кратко:\n\n{lead}\n\n{detail}"


def _strip_status_footer(text: str) -> str:
    """Убирает «Статус:» / «Вступление в силу:» — они есть в справочной колонке Word."""
    parts = []
    for block in text.split("\n\n"):
        low = block.strip().lower()
        if low.startswith("статус:") or low.startswith("вступление в силу:"):
            continue
        parts.append(block)
    return "\n\n".join(parts).strip()


def sanitize_key_changes(
    key_changes: str,
    *,
    doc_title: str = "",
    doc_stage: str | None = None,
    source_text: str = "",
) -> str:
    """Убирает отмазки, артефакты промпта, плейсхолдеры; корректирует формулировки."""
    body = (key_changes or "").strip()
    if not body:
        return body

    if body.lower().startswith("кратко:"):
        prefix, rest = "Кратко:", body[7:].lstrip()
    else:
        prefix, rest = "Кратко:", body

    paragraphs = [p.strip() for p in rest.split("\n\n") if p.strip()]
    clean: list[str] = []
    for paragraph in paragraphs:
        low = paragraph.lower()
        if low.startswith("статус:") or low.startswith("вступление в силу:"):
            continue
        cleaned = _clean_paragraph(paragraph, source_text)
        if cleaned and not _sentence_has_issue(cleaned, source_text):
            clean.append(cleaned)

    merged = _fix_pending_wording("\n\n".join(clean), doc_stage)
    result = f"{prefix}\n\n{merged}" if prefix and merged else (f"{prefix}\n\n" if prefix else merged)

    if is_weak_analysis(result, doc_title, source_text):
        result = build_smart_fallback(
            doc_title=doc_title,
            doc_stage=doc_stage,
            source_text=source_text,
        )
    return result


def normalize_stage(stage: str | None) -> str:
    value = (stage or "").strip()
    if value.lower() in _GARBAGE_STAGES:
        return ""
    return value


def resolve_adoption_status(
    doc_stage: str | None,
    llm_status: str = "",
) -> str:
    """Статус документа: приоритет у данных ingest, LLM — запасной вариант."""
    stage = normalize_stage(doc_stage)
    if stage:
        return stage
    llm = (llm_status or "").strip()
    if llm.lower() not in ("", "не указана", "—", "-"):
        return llm
    return ""


def build_brief_changes_text(
    key_changes: str,
    adoption_status: str = "",
    effective_date: str = "",
    *,
    for_export: bool = False,
) -> str:
    """Краткая суть изменений для memo / колонки «Результат рассмотрения»."""
    body = key_changes.strip()
    if body and not body.lower().startswith("кратко:"):
        body = f"Кратко:\n{body}"

    parts: list[str] = []
    if body:
        parts.append(body)

    if not for_export:
        status = adoption_status.strip()
        if status and status.lower() not in ("не указана", "—", "-"):
            parts.append(f"Статус: {status}")
        if effective_date.strip() and effective_date.strip().lower() not in ("не указана", "—", "-"):
            parts.append(f"Вступление в силу: {effective_date.strip()}")

    return "\n\n".join(parts) if parts else "—"


def get_export_changes_text(doc: Document, memo: Memo | None, with_analysis: bool) -> str:
    """Текст для колонки «Результат рассмотрения» в Excel/Word."""
    if not with_analysis or not memo:
        return "—"

    raw = (memo.key_changes or memo.legal_analysis or "").strip()
    if not raw:
        return "—"

    source = (doc.text or "").strip()
    if not source and doc.title:
        source = doc.title
    title = doc.title or ""

    text = sanitize_key_changes(
        raw,
        doc_title=title,
        doc_stage=doc.stage,
        source_text=source,
    )
    text = _strip_status_footer(text)

    if (
        is_stub_analysis(text)
        or contains_prompt_artifact(text, source)
        or contains_placeholder_garbage(text)
        or is_title_paraphrase(text, title)
    ):
        text = build_smart_fallback(
            doc_title=title,
            doc_stage=doc.stage,
            source_text=source,
        )

    if is_stub_analysis(text) or contains_prompt_artifact(text, source):
        return "—"
    return text.strip() or "—"


def build_legal_analysis(
    doc: Document,
    summary: str,
    key_changes: str,
    adoption_status: str = "",
    effective_date: str = "",
) -> str:
    """Полный текст для memo (внутренний)."""
    return build_brief_changes_text(key_changes, adoption_status, effective_date)
