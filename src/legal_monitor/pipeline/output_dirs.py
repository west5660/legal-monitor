from __future__ import annotations

from pathlib import Path

from legal_monitor.config import Settings


def output_dirs(settings: Settings) -> dict[str, Path]:
    """Структура output/: excel, word, review (HTML-отбор), selected (отобранные с анализом)."""
    root = settings.output_dir.resolve()
    dirs = {
        "root": root,
        "excel": root / "excel",
        "word": root / "word",
        "review": root / "review",
        "selected": root / "selected",
    }
    for key in ("excel", "word", "review", "selected"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    return dirs
