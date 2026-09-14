from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from legal_monitor.config import Settings
from legal_monitor.pipeline.export import regenerate_review_bundle
from legal_monitor.pipeline.output_dirs import output_dirs

logger = logging.getLogger(__name__)

STAMP_RE = re.compile(r"^(\d{8}_\d{6})_")

KEEP_IN_ROOT = frozenset(
    {
        ".gitkeep",
        ".migrated_layout",
        "ingest_report.json",
        "parser_benchmark.json",
        "export_review_latest.json",
        "analysis_review.json",
        "analysis_review_detail.json",
    }
)


@dataclass
class MigrateResult:
    moved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    review_created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "moved": self.moved,
            "skipped": self.skipped,
            "review_created": self.review_created,
            "errors": self.errors,
        }


def extract_export_stamp(filename: str) -> str | None:
    match = STAMP_RE.match(filename)
    return match.group(1) if match else None


def _docx_target_dir(dirs: dict[str, Path], name: str) -> Path:
    if "отобранные" in name.lower():
        return dirs["selected"]
    return dirs["word"]


def _resolve_dest(dirs: dict[str, Path], path: Path) -> Path | None:
    name = path.name
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return dirs["excel"] / name
    if ext == ".docx":
        return _docx_target_dir(dirs, name) / name
    if ext == ".html" and name.endswith("_review.html"):
        return dirs["review"] / name
    if name.endswith("_rows.json"):
        return dirs["review"] / name
    return None


def migrate_output_layout(
    settings: Settings,
    *,
    dry_run: bool = False,
    create_review: bool = True,
) -> MigrateResult:
    """Перенос legacy-файлов из корня output/ в подпапки + review JSON для списков."""
    dirs = output_dirs(settings)
    root = dirs["root"]
    result = MigrateResult()

    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name in KEEP_IN_ROOT:
            continue
        dest = _resolve_dest(dirs, path)
        if dest is None:
            continue
        if dest.exists():
            result.skipped.append(f"{path.name} (уже есть {dest.relative_to(root)})")
            continue
        rel = dest.relative_to(root)
        if dry_run:
            result.moved.append(f"{path.name} -> {rel.as_posix()}")
            continue
        try:
            path.rename(dest)
            result.moved.append(f"{path.name} -> {rel.as_posix()}")
        except OSError as exc:
            result.errors.append(f"{path.name}: {exc}")

    if create_review:
        for xlsx in sorted(dirs["excel"].glob("*.xlsx")):
            if "_анализ" in xlsx.name:
                continue
            stamp = extract_export_stamp(xlsx.name)
            if not stamp:
                continue
            json_path = dirs["review"] / f"{stamp}_rows.json"
            if json_path.is_file():
                continue
            if dry_run:
                result.review_created.append(stamp)
                continue
            try:
                created = regenerate_review_bundle(settings, stamp)
                if created:
                    result.review_created.append(stamp)
            except Exception as exc:
                result.errors.append(f"review {stamp}: {exc}")

    if not dry_run and (result.moved or result.review_created):
        marker = root / ".migrated_layout"
        marker.write_text("ok\n", encoding="utf-8")

    return result


def run_migrate_output(settings: Settings, *, dry_run: bool = False) -> MigrateResult:
    """CLI / startup entry: idempotent migration."""
    result = migrate_output_layout(settings, dry_run=dry_run)
    if result.moved:
        logger.info("Миграция output: перенесено %s файлов", len(result.moved))
    if result.review_created:
        logger.info("Миграция output: создано review-сессий: %s", len(result.review_created))
    if result.skipped:
        logger.debug("Миграция output: пропущено %s", len(result.skipped))
    for err in result.errors:
        logger.warning("Миграция output: %s", err)
    return result
