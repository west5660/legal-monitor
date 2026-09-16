"""Covers the detectors that catch weak/contaminated LLM output. The LLM
analysis pipeline itself (pipeline/analyze.py, llm.py) was removed from the
project - the user stopped using any LLM provider - but these detectors and
`sanitize_key_changes`/`get_export_changes_text` stay: they're what renders
any memo rows left over from before in exports without surfacing garbage,
and `contains_prompt_artifact`/`is_weak_analysis` are exactly what should
flag the real failure mode found during the pre-removal audit (the literal
"13% до 15%" prompt example leaking into an unrelated document's analysis)
if similar contamination is ever found in that legacy data.
"""
from __future__ import annotations

import pytest

from legal_monitor.analysis_text import (
    contains_prompt_artifact,
    is_stub_analysis,
    is_weak_analysis,
    sanitize_key_changes,
)


def test_prompt_artifact_detected_when_not_in_source():
    # The exact real-world case from output/analysis_review_detail.json:
    # "13% до 15%" leaking into a document that never mentions it.
    text = "Кратко:\n\nСтавка налога повышена с 13% до 15% для указанной категории."
    source_text = "Настоящий документ вносит изменения в Бюджетный кодекс в части межбюджетных трансфертов."
    assert contains_prompt_artifact(text, source_text) is True


def test_prompt_artifact_not_flagged_when_figure_is_genuinely_in_source():
    text = "Кратко:\n\nСтавка налога повышена с 13% до 15% для указанной категории."
    source_text = "Ставка налога повышена с 13% до 15% для отдельной категории плательщиков."
    assert contains_prompt_artifact(text, source_text) is False


def test_stub_analysis_detected():
    assert is_stub_analysis("") is True
    assert is_stub_analysis(None) is True
    assert is_stub_analysis("—") is True
    assert is_stub_analysis("LLM-анализ не выполнен") is True
    assert is_stub_analysis("Кратко:\n\nДокумент вносит конкретные изменения в порядок учёта.") is False


def test_weak_analysis_flags_too_short_body():
    # Body after "Кратко:" under 40 chars is treated as weak.
    assert is_weak_analysis("Кратко:\n\nКоротко.", "Название", "") is True


def test_weak_analysis_accepts_substantive_text():
    text = (
        "Кратко:\n\nДокумент вносит изменения в порядок расчёта пособия "
        "по временной нетрудоспособности для отдельной категории работников."
    )
    assert is_weak_analysis(text, "Название документа", "") is False


def test_sanitize_key_changes_falls_back_when_result_becomes_weak():
    # A key_changes dominated by a hedge phrase should be replaced by the
    # smart fallback rather than surfaced to the user as-is.
    result = sanitize_key_changes(
        "Кратко:\n\nдокумент не содержит конкретных изменений",
        doc_title="Закон о чём-то важном для целей теста",
        doc_stage="Опубликован",
        source_text="В тексте документа упоминается порядок и процедура рассмотрения обращений.",
    )
    assert result.lower().startswith("кратко:")
    assert "не содержит конкретных изменений" not in result.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
