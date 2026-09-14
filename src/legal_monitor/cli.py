from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from legal_monitor.config import load_profiles, load_settings
from legal_monitor.llm import ensure_ollama_model
from legal_monitor.utils import _ensure_tesseract_env, _get_tessdata_dir
from legal_monitor.pipeline.analyze import run_analyze
from legal_monitor.pipeline.classify import run_classify
from legal_monitor.pipeline.export import run_cleanup, run_export_flow
from legal_monitor.pipeline.migrate_output import run_migrate_output
from legal_monitor.pipeline.ingest import get_last_ingest_runs, run_ingest
from legal_monitor.progress import create_progress

app = typer.Typer(help="Юридический мониторинг законодательства")
console = Console()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _print_ingest_stats(stats: dict, settings=None) -> None:
    table = Table(title="Скачивание по источникам")
    table.add_column("Источник")
    table.add_column("Сайт")
    table.add_column("Найдено", justify="right")
    table.add_column("Новых", justify="right")
    table.add_column("Обновлено", justify="right")
    table.add_column("Статус")

    for name, src in stats.get("sources", {}).items():
        status = "[green]OK[/green]" if src["status"] == "ok" else f"[red]ОШИБКА[/red]"
        table.add_row(
            name,
            src["site"],
            str(src["fetched"]),
            str(src["new"]),
            str(src["updated"]),
            status,
        )

    console.print(table)
    console.print(
        f"[bold]Итого:[/bold] найдено={stats['fetched']}, "
        f"новых={stats['new']}, обновлено={stats['updated']}, ошибок={stats['errors']}"
    )
    if settings:
        report_path = settings.output_dir / "ingest_report.json"
        console.print(f"[dim]Подробный отчёт:[/dim] {report_path}")


def _print_export_flow(result) -> None:
    le = result.list_export
    console.print(f"[green]Список Excel:[/green] {le.excel}")
    console.print(f"[green]Список Word:[/green]  {le.word}")
    if result.analysis_export:
        ae = result.analysis_export
        console.print(f"[green]Анализ Excel:[/green] {ae.excel}")
        console.print(f"[green]Анализ Word:[/green]  {ae.word}")


@app.command()
def ingest():
    """Скачать документы за последние 2 недели."""
    settings = load_settings()
    with create_progress(console) as progress:
        stats = run_ingest(settings, progress=progress)
    _print_ingest_stats(stats, settings)


@app.command()
def classify():
    """Классифицировать документы по зонам интереса (опубликованные за 14 дней)."""
    settings = load_settings()
    with create_progress(console) as progress:
        stats = run_classify(settings, progress=progress)
    console.print(f"[green]Готово:[/green] {stats}")


@app.command()
def analyze():
    """LLM-анализ shortlist (опубликовано за 14 дней + профили)."""
    settings = load_settings()
    with create_progress(console) as progress:
        stats = run_analyze(settings, progress=progress)
    console.print(
        f"[green]Готово:[/green] обработано={stats['processed']}, "
        f"memo={stats['memos_created']}, LLM={stats['llm_used']}, "
        f"пропущено={stats.get('skipped', 0)}"
    )


@app.command()
def export(
    with_analysis: bool = typer.Option(
        False,
        "--analyze/--no-analyze",
        help="Сразу выполнить LLM-анализ и сохранить вторую выгрузку _анализ",
    ),
):
    """Экспорт shortlist: список + опционально выгрузка _анализ."""
    settings = load_settings()
    if with_analysis:
        with create_progress(console) as progress:
            result = run_export_flow(
                settings,
                progress=progress,
                ask_analyze=False,
                run_analysis=True,
            )
    else:
        result = run_export_flow(settings, progress=None, ask_analyze=True)
    _print_export_flow(result)


@app.command("migrate-output")
def migrate_output_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Только показать, что будет сделано"),
):
    """Перенести старые выгрузки из output/ в подпапки excel/word/review/selected."""
    settings = load_settings()
    result = run_migrate_output(settings, dry_run=dry_run)
    if result.moved:
        console.print("[green]Перенесено:[/green]")
        for line in result.moved:
            console.print(f"  {line}")
    if result.review_created:
        console.print("[green]Созданы review-сессии:[/green] " + ", ".join(result.review_created))
    if result.skipped:
        console.print(f"[dim]Пропущено (уже на месте): {len(result.skipped)}[/dim]")
    if result.errors:
        for err in result.errors:
            console.print(f"[red]{err}[/red]")
    if not any((result.moved, result.review_created, result.skipped, result.errors)):
        console.print("[green]Миграция не требуется — структура output/ актуальна.[/green]")


@app.command()
def cleanup():
    """Удалить старые данные (пакет 2 недели)."""
    settings = load_settings()
    stats = run_cleanup(settings)
    console.print(f"[green]Cleanup:[/green] {stats}")


@app.command()
def full(
    with_analysis: bool = typer.Option(
        False,
        "--analyze/--no-analyze",
        help="После выгрузки списка выполнить LLM-анализ",
    ),
):
    """Полный цикл: ingest → classify → export → опц. analyze."""
    settings = load_settings()
    with create_progress(console) as progress:
        stats = run_ingest(settings, progress=progress)
        run_classify(settings, progress=progress)
    if with_analysis:
        with create_progress(console) as progress:
            result = run_export_flow(
                settings,
                progress=progress,
                ask_analyze=False,
                run_analysis=True,
            )
    else:
        result = run_export_flow(settings, progress=None, ask_analyze=True)
    _print_ingest_stats(stats, settings)
    console.print("[bold green]Полный цикл завершён.[/bold green]")
    _print_export_flow(result)


@app.command("sources")
def sources_cmd():
    """История скачивания: с каких сайтов и сколько документов."""
    settings = load_settings()
    runs = get_last_ingest_runs(settings, limit=30)
    if not runs:
        console.print("[yellow]Ещё не было скачиваний. Запустите:[/yellow] legal-monitor ingest")
        return

    table = Table(title="Последние запуски скачивания")
    table.add_column("Время")
    table.add_column("Источник")
    table.add_column("Сайт")
    table.add_column("Найдено", justify="right")
    table.add_column("Новых", justify="right")
    table.add_column("Статус")

    for run in runs:
        started = run["started_at"][:19].replace("T", " ")
        status = "[green]OK[/green]" if not run["error"] else "[red]ОШИБКА[/red]"
        table.add_row(
            started,
            run["source"],
            run["site"],
            str(run["fetched"]),
            str(run["new"]),
            status,
        )

    console.print(table)
    report_path = settings.output_dir / "ingest_report.json"
    if report_path.exists():
        console.print(f"\n[dim]Последний отчёт:[/dim] {report_path}")


@app.command("ocr-setup")
def ocr_setup():
    """Проверить Tesseract OCR и языковые данные (rus) для PDF pravo.gov.ru."""
    if not _ensure_tesseract_env():
        console.print(
            "[red]Tesseract не найден.[/red] Установите: "
            "[bold]winget install UB-Mannheim.TesseractOCR[/bold]"
        )
        raise typer.Exit(1)
    tessdata = _get_tessdata_dir()
    langs = [p.stem for p in tessdata.glob("*.traineddata")]
    console.print(f"[green]Tesseract OK[/green]")
    console.print(f"[dim]tessdata:[/dim] {tessdata}")
    console.print(f"[dim]языки:[/dim] {', '.join(sorted(langs))}")
    if "rus" not in langs:
        console.print("[yellow]Предупреждение:[/yellow] rus.traineddata не найден")


@app.command("ollama-setup")
def ollama_setup():
    """Скачать модель Ollama для LLM-анализа."""
    settings = load_settings()
    if settings.llm_provider != "ollama":
        console.print(
            "[yellow]В .env установлен LLM_PROVIDER="
            f"{settings.llm_provider}. Для Ollama задайте LLM_PROVIDER=ollama[/yellow]"
        )
        return
    try:
        model = ensure_ollama_model(settings)
        console.print(f"[green]Ollama готова. Модель:[/green] {model}")
    except Exception as exc:
        console.print(f"[red]Ошибка:[/red] {exc}")


@app.command("web")
def web_ui():
    """Запустить API + фронт + браузер (одной командой)."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "start_web.py"
    raise SystemExit(subprocess.call([sys.executable, str(script)]))


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Хост API"),
    port: int = typer.Option(8000, help="Порт API"),
):
    """Запустить Web API (фронт: cd web && npm run dev)."""
    import uvicorn

    console.print(f"[green]API:[/green] http://{host}:{port}")
    console.print("[dim]Frontend:[/dim] cd web && npm run dev  (http://localhost:5173)")
    uvicorn.run("legal_monitor.web.app:app", host=host, port=port, reload=False)


@app.command()
def profiles():
    """Показать активные зоны интереса."""
    table = Table(title="Зоны интереса")
    table.add_column("ID")
    table.add_column("Название")
    table.add_column("Статус")
    table.add_column("Ключевые слова")

    for p in load_profiles():
        table.add_row(
            p.id,
            p.name,
            "ВКЛ" if p.enabled else "ВЫКЛ",
            ", ".join(p.rules.keywords_any[:5]),
        )
    console.print(table)
