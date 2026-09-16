from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from rich.progress import Progress
from sqlalchemy.orm import joinedload

from legal_monitor.analysis_text import get_export_changes_text
from legal_monitor.config import Settings
from legal_monitor.models import Document, DocumentProfile, Memo, init_db
from legal_monitor.monitoring import (
    format_monitoring_period,
    get_monitoring_window,
    query_monitoring_matches,
)
from legal_monitor.pipeline.output_dirs import output_dirs
from legal_monitor.pipeline.review import rows_to_review_payload, save_review_bundle
from legal_monitor.progress import start_step

logger = logging.getLogger(__name__)

COLUMNS = [
    "Дата публикации",
    "Профиль",
    "Релевантность",
    "Источник",
    "Тип",
    "Номер/ID",
    "Название",
    "Стадия",
    "Ссылка",
    "Результат рассмотрения (суть изменений)",
    "Краткое содержание",
    "Ключевые изменения",
    "Влияние",
    "Риски",
    "Memo (полный текст)",
    "Статус",
    "Дата анализа",
]


@dataclass
class ExportPaths:
    excel: Path
    word: Path
    rows: int
    stamp: str
    with_analysis: bool
    review_html: Path | None = None
    review_json: Path | None = None


@dataclass
class ExportFlowResult:
    list_export: ExportPaths


def new_export_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _unique_file_path(directory: Path, filename: str) -> Path:
    """Не перезаписывать существующий файл — добавить суффикс _2, _3, …"""
    path = directory / filename
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = directory / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def run_export(
    settings: Settings,
    *,
    with_analysis: bool = False,
    stamp: str | None = None,
    progress: Progress | None = None,
) -> ExportPaths:
    """Выгрузка shortlist: опубликовано за 14 дней + профили."""
    export_stamp = stamp or new_export_stamp()
    Session = init_db(str(settings.db_path))
    session = Session()
    date_from, date_to = get_monitoring_window(settings)
    label = "анализ" if with_analysis else "список"
    step = start_step(progress, "", 0)
    excel_path = word_path = None

    try:
        rows = _collect_export_rows(session, settings)
        grouped = _group_rows_by_document(rows)
        total_steps = len(rows) + max(len(grouped), 1)
        step = start_step(
            progress,
            f"Экспорт {label} ({format_monitoring_period(settings)})",
            total_steps,
        )

        excel_path = _export_excel(settings, rows, step, with_analysis, export_stamp)
        word_path = _export_word(
            settings, grouped, date_from, date_to, step, with_analysis, export_stamp
        )
        review_json = review_html = None
        if not with_analysis and rows:
            payload = rows_to_review_payload(settings, export_stamp, rows, date_from, date_to)
            review_json, review_html = save_review_bundle(settings, payload)
    finally:
        step.finish()
        session.close()

    logger.info(
        "Экспорт %s (опубликовано %s — %s): Excel=%s, Word=%s, строк=%s",
        label,
        date_from,
        date_to,
        excel_path,
        word_path,
        len(rows),
    )
    return ExportPaths(
        excel=excel_path,
        word=word_path,
        rows=len(rows),
        stamp=export_stamp,
        with_analysis=with_analysis,
        review_html=review_html,
        review_json=review_json,
    )


def _count_shortlist_documents(session, settings: Settings) -> int:
    matches = query_monitoring_matches(session, settings).all()
    return len({doc.id for _, doc in matches})


def run_export_flow(
    settings: Settings,
    progress: Progress | None = None,
) -> ExportFlowResult:
    """Выгрузка shortlist (список за период мониторинга) в Excel/Word.

    Раньше здесь была вторая, опциональная фаза: спросить пользователя,
    запустить ли LLM-анализ (в интерактивном режиме — вопросом «д/н» в
    консоли), и если да — прогнать run_analyze() и сохранить вторую
    выгрузку «_анализ». LLM-анализ убран из проекта целиком (пользователь
    отказался от LLM), так что эта фаза убрана вместе с ним — выгрузка
    всегда единственная, без вопроса и без второго файла.
    """
    stamp = new_export_stamp()
    list_export = run_export(settings, with_analysis=False, stamp=stamp, progress=progress)
    return ExportFlowResult(list_export=list_export)


def regenerate_review_bundle(settings: Settings, stamp: str) -> tuple[Path, Path] | None:
    """Создать review JSON/HTML для stamp из текущего shortlist (миграция старых выгрузок)."""
    Session = init_db(str(settings.db_path))
    session = Session()
    date_from, date_to = get_monitoring_window(settings)
    try:
        rows = _collect_export_rows(session, settings)
        if not rows:
            return None
        payload = rows_to_review_payload(settings, stamp, rows, date_from, date_to)
        return save_review_bundle(settings, payload)
    finally:
        session.close()


def _collect_export_rows(session, settings: Settings) -> list[tuple[Document, Memo | None, DocumentProfile]]:
    matches = query_monitoring_matches(session, settings).all()
    if not matches:
        return []

    memo_map: dict[tuple[int, str], Memo] = {}
    for memo in session.query(Memo).options(joinedload(Memo.document)).all():
        memo_map[(memo.document_id, memo.profile_id)] = memo

    rows: list[tuple[Document, Memo | None, DocumentProfile]] = []
    for match, doc in matches:
        memo = memo_map.get((doc.id, match.profile_id))
        rows.append((doc, memo, match))
    return rows


def _export_filename(stamp: str, period: str, with_analysis: bool, ext: str) -> str:
    suffix = "_анализ" if with_analysis else ""
    if ext == "xlsx":
        return f"{stamp}_legal_monitor_{period}{suffix}.xlsx"
    return f"{stamp}_Мониторинг_{period}{suffix}.docx"


def _export_excel(
    settings: Settings,
    rows: list,
    step,
    with_analysis: bool,
    stamp: str,
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Юридический мониторинг"

    header_font = Font(bold=True)
    for col, name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    for row_idx, (doc, memo, match) in enumerate(rows, start=2):
        _write_excel_row(ws, row_idx, doc, memo, match, with_analysis)
        step.advance(1, description="Экспорт Excel…")

    if not rows:
        step.advance(1, description="Экспорт Excel: нет данных")

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    ws.column_dimensions["G"].width = 40
    ws.column_dimensions["J"].width = 55
    ws.column_dimensions["O"].width = 50

    period = format_monitoring_period(settings)
    filename = _export_filename(stamp, period, with_analysis, "xlsx")
    out_path = output_dirs(settings)["excel"] / filename
    wb.save(out_path)
    return out_path


def _write_excel_row(
    ws,
    row_idx: int,
    doc: Document,
    memo: Memo | None,
    match: DocumentProfile | None,
    with_analysis: bool,
):
    changes_text = get_export_changes_text(doc, memo, with_analysis)
    values = [
        str(doc.register_date or ""),
        memo.profile_name if memo else (match.profile_name if match else ""),
        match.relevance_score if match else "",
        doc.source,
        doc.doc_type or "",
        doc.external_id,
        doc.title,
        doc.stage or "",
        doc.url or "",
        changes_text,
        memo.summary if memo and with_analysis else "",
        memo.key_changes if memo and with_analysis else "",
        memo.impact if memo and with_analysis else "",
        memo.risks if memo and with_analysis else "",
        memo.memo_markdown if memo and with_analysis else "",
        memo.status if memo else ("черновик" if with_analysis else "список"),
        str(memo.created_at.date() if memo and with_analysis else ""),
    ]
    for col, value in enumerate(values, start=1):
        ws.cell(row=row_idx, column=col, value=value).alignment = Alignment(wrap_text=True, vertical="top")


def _export_word(
    settings: Settings,
    grouped: list[tuple[Document, list[tuple[Memo | None, DocumentProfile]]]],
    date_from: date,
    date_to: date,
    step,
    with_analysis: bool,
    stamp: str,
) -> Path:
    word_dir = output_dirs(settings)["word"]

    period = format_monitoring_period(settings)
    filename = _export_filename(stamp, period, with_analysis, "docx")
    out_path = word_dir / filename

    docx = DocxDocument()
    title_suffix = " (анализ)" if with_analysis else ""
    title = docx.add_heading(f"Мониторинг законодательства ({period}){title_suffix}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = docx.add_paragraph(
        f"Опубликовано: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"
    )
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    docx.add_paragraph("")

    row_count = max(len(grouped), 1)
    table = docx.add_table(rows=1 + row_count, cols=5)
    table.style = "Table Grid"

    headers = ["№", "Название", "Справочная информация", "Результат рассмотрения", "Примечание"]
    header_cells = table.rows[0].cells
    for idx, text in enumerate(headers):
        header_cells[idx].text = text
        for paragraph in header_cells[idx].paragraphs:
            for run in paragraph.runs:
                run.bold = True

    for num, (doc, doc_rows) in enumerate(grouped, start=1):
        row_cells = table.rows[num].cells
        row_cells[0].text = str(num)
        row_cells[1].text = doc.title or "—"
        row_cells[2].text = _format_reference_info(doc, doc_rows)
        row_cells[3].text = _format_review_result(doc, doc_rows, with_analysis)
        row_cells[4].text = _format_note(doc, doc_rows, with_analysis)
        step.advance(1, description="Экспорт Word…")

    if not grouped:
        empty = table.rows[1].cells
        empty[0].text = "—"
        empty[1].text = "Нет актов, опубликованных за период мониторинга"
        for idx in range(2, 5):
            empty[idx].text = "—"
        step.advance(1, description="Экспорт Word…")

    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(4)
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    docx.sections[0].left_margin = Cm(1.5)
    docx.sections[0].right_margin = Cm(1.5)
    docx.save(out_path)
    return out_path


def _group_rows_by_document(
    rows: list[tuple[Document, Memo | None, DocumentProfile]],
) -> list[tuple[Document, list[tuple[Memo | None, DocumentProfile]]]]:
    grouped: dict[int, tuple[Document, list]] = {}
    order: list[int] = []
    for doc, memo, match in rows:
        if doc.id not in grouped:
            grouped[doc.id] = (doc, [])
            order.append(doc.id)
        grouped[doc.id][1].append((memo, match))
    return [grouped[doc_id] for doc_id in order]


def _format_reference_info(doc: Document, doc_rows: list[tuple[Memo | None, DocumentProfile]]) -> str:
    profiles = ", ".join(match.profile_name for _, match in doc_rows)
    parts = [
        f"Тип: {doc.doc_type or '—'}",
        f"№/ID: {doc.external_id}",
        f"Дата публикации: {doc.register_date.strftime('%d.%m.%Y') if doc.register_date else '—'}",
        f"Источник: {doc.source}",
        f"Стадия: {doc.stage or '—'}",
        f"Зоны интереса: {profiles}",
    ]
    if doc.url:
        parts.append(f"Ссылка: {doc.url}")
    if doc.initiator:
        parts.append(f"Инициатор: {doc.initiator[:300]}")
    return "\n".join(parts)


def _format_review_result(
    doc: Document,
    doc_rows: list[tuple[Memo | None, DocumentProfile]],
    with_analysis: bool,
) -> str:
    if not with_analysis:
        return "—"
    seen: set[str] = set()
    parts: list[str] = []
    for memo, _match in doc_rows:
        text = get_export_changes_text(doc, memo, True)
        if text == "—" or text in seen:
            continue
        seen.add(text)
        parts.append(text)
    return "\n\n".join(parts) if parts else "—"


def _format_note(
    doc: Document,
    doc_rows: list[tuple[Memo | None, DocumentProfile]],
    with_analysis: bool,
) -> str:
    if not with_analysis:
        return "—"
    parts = []
    for memo, match in doc_rows:
        if memo and memo.impact:
            parts.append(f"«{match.profile_name}»: {memo.impact}")
        elif memo and memo.risks:
            parts.append(f"«{match.profile_name}»: {memo.risks}")
    return "\n".join(parts) if parts else "—"


def run_export_selected(
    settings: Settings,
    selections: list[dict[str, int | str]],
    stamp: str | None = None,
    progress: Progress | None = None,
) -> ExportPaths:
    """Word-выгрузка только отобранных (вручную, на странице «Отбор») строк."""
    if not selections:
        raise ValueError("Не выбрано ни одной строки")

    # Каждый запуск отбора — отдельный файл (не перезаписываем прошлые выгрузки).
    export_stamp = new_export_stamp()
    wanted = {(int(s["document_id"]), str(s["profile_id"])) for s in selections}

    Session = init_db(str(settings.db_path))
    session = Session()
    date_from, date_to = get_monitoring_window(settings)
    step = start_step(progress, "Экспорт отобранных", 1)

    try:
        all_rows = _collect_export_rows(session, settings)
        rows = [
            (doc, memo, match)
            for doc, memo, match in all_rows
            if (doc.id, match.profile_id) in wanted
        ]
        grouped = _group_rows_by_document(rows)
        step = start_step(progress, "Экспорт отобранных", max(len(grouped), 1))
        word_path = _export_word_selected(
            settings,
            grouped,
            date_from,
            date_to,
            step,
            export_stamp,
            review_stamp=stamp,
        )
    finally:
        step.finish()
        session.close()

    return ExportPaths(
        excel=word_path,
        word=word_path,
        rows=len(rows),
        stamp=export_stamp,
        with_analysis=True,
    )


def _export_word_selected(
    settings: Settings,
    grouped: list[tuple[Document, list[tuple[Memo | None, DocumentProfile]]]],
    date_from: date,
    date_to: date,
    step,
    stamp: str,
    review_stamp: str | None = None,
) -> Path:
    selected_dir = output_dirs(settings)["selected"]
    period = format_monitoring_period(settings)
    filename = f"{stamp}_отобранные_{period}.docx"
    out_path = _unique_file_path(selected_dir, filename)

    docx = DocxDocument()
    title = docx.add_heading(f"Отобранные документы ({period})", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = (
        f"Опубликовано: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"
        f" · выгрузка {stamp}"
    )
    if review_stamp:
        meta += f" · сессия отбора {review_stamp}"
    docx.add_paragraph(meta).alignment = WD_ALIGN_PARAGRAPH.CENTER
    docx.add_paragraph("")

    row_count = max(len(grouped), 1)
    table = docx.add_table(rows=1 + row_count, cols=5)
    table.style = "Table Grid"
    headers = ["№", "Название", "Справочная информация", "Результат рассмотрения", "Примечание"]
    for idx, text in enumerate(headers):
        table.rows[0].cells[idx].text = text

    for num, (doc, doc_rows) in enumerate(grouped, start=1):
        row_cells = table.rows[num].cells
        row_cells[0].text = str(num)
        row_cells[1].text = doc.title or "—"
        row_cells[2].text = _format_reference_info(doc, doc_rows)
        row_cells[3].text = _format_review_result(doc, doc_rows, True)
        row_cells[4].text = _format_note(doc, doc_rows, True)
        step.advance(1, description="Word отобранные…")

    docx.save(out_path)
    logger.info("Отобранные сохранены: %s", out_path.name)
    return out_path


def run_cleanup(settings: Settings) -> dict[str, int]:
    """Удалить документы и их файлы старше окна хранения.

    Обработка каждого документа изолирована: если для одного документа не
    удалось удалить файлы (например, файл открыт/заблокирован на Windows),
    это не прерывает весь пакетный запуск — документ просто пропускается и
    будет обработан повторно в следующем запуске, а остальные документы пакета
    обрабатываются как обычно. Строка БД документа удаляется только после успешного
    удаления его файлов (или если файлов и не было), чтобы не оставлять в БД
    записи, ссылающиеся на уже несуществующие папки.
    """
    Session = init_db(str(settings.db_path))
    session = Session()

    cutoff = date.today() - timedelta(days=settings.retention_days)
    batch_start = cutoff - timedelta(days=settings.cleanup_batch_days)

    stats = {"deleted_docs": 0, "deleted_files": 0, "failed": 0}

    try:
        old_docs = (
            session.query(Document)
            .filter(Document.register_date.isnot(None))
            .filter(Document.register_date >= batch_start)
            .filter(Document.register_date < cutoff)
            .all()
        )

        for doc in old_docs:
            try:
                if doc.files_path:
                    folder = Path(doc.files_path)
                    if folder.exists() and folder.is_dir():
                        for f in folder.iterdir():
                            f.unlink(missing_ok=True)
                        folder.rmdir()
                        stats["deleted_files"] += 1
            except OSError as exc:
                logger.warning(
                    "Cleanup: не удалось удалить файлы документа id=%s (%s) — "
                    "документ пропущен, попытка повторится в следующем запуске",
                    getattr(doc, "id", None),
                    exc,
                )
                stats["failed"] += 1
                continue

            session.delete(doc)
            stats["deleted_docs"] += 1

        session.commit()
    finally:
        session.close()

    logger.info(
        "Cleanup: удалено документов=%s (период %s — %s), папок=%s, пропущено из-за ошибок=%s",
        stats["deleted_docs"],
        batch_start,
        cutoff,
        stats["deleted_files"],
        stats["failed"],
    )
    return stats
