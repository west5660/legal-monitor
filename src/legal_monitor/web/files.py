from __future__ import annotations



import base64

import mimetypes

from dataclasses import dataclass

from datetime import datetime

from pathlib import Path



from legal_monitor.config import Settings

from legal_monitor.pipeline.output_dirs import output_dirs





@dataclass

class FileEntry:

    id: str

    name: str

    path: str

    category: str

    size: int

    modified_at: str

    extension: str



    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "name": self.name,

            "path": self.path,

            "category": self.category,

            "size": self.size,

            "modified_at": self.modified_at,

            "extension": self.extension,

        }





def _encode_id(root_key: str, rel: Path) -> str:

    raw = f"{root_key}:{rel.as_posix()}"

    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")





def _decode_id(file_id: str) -> tuple[str, str]:

    pad = "=" * (-len(file_id) % 4)

    raw = base64.urlsafe_b64decode(file_id + pad).decode()

    root_key, rel = raw.split(":", 1)

    return root_key, rel





def _allowed_roots(settings: Settings) -> dict[str, Path]:

    return {

        "output": settings.output_dir.resolve(),

        "downloads": settings.downloads_dir.resolve(),

    }





def resolve_relative_file(settings: Settings, root_key: str, rel_path: str) -> Path:
    roots = _allowed_roots(settings)
    if root_key not in roots:
        raise ValueError("Недопустимая категория файла")
    base = roots[root_key]
    rel = Path(rel_path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Недопустимая относительная path")
    path = (base / rel).resolve()
    if str(path).startswith(str(base)) and path.is_file():
        return path
    if root_key == "output":
        found = _resolve_output_fallback(settings, base, rel)
        if found is not None:
            return found
        # последний шанс: поиск по имени в output/
        name = rel.name
        if name:
            matches = [p for p in base.rglob(name) if p.is_file()]
            if len(matches) == 1:
                return matches[0].resolve()
            for sub in ("excel", "word", "selected", "review"):
                candidate = (base / sub / name).resolve()
                if candidate.is_file() and str(candidate).startswith(str(base)):
                    return candidate
    raise FileNotFoundError("Файл не найден")


def resolve_file_path(settings: Settings, file_id: str) -> Path:
    root_key, rel = _decode_id(file_id)
    return resolve_relative_file(settings, root_key, rel)


def _resolve_output_fallback(settings: Settings, base: Path, rel: Path) -> Path | None:
    """Совместимость: файлы после миграции в подпапках, id может содержать только имя."""
    dirs = output_dirs(settings)
    name = rel.name
    candidates = [
        base / rel,
        dirs["excel"] / name,
        dirs["word"] / name,
        dirs["selected"] / name,
        dirs["review"] / name,
        base / "excel" / name,
        base / "word" / name,
        base / "selected" / name,
    ]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and str(resolved).startswith(str(base)):
                return resolved
        except OSError:
            continue
    return None





def _entry_from_path(root: Path, root_key: str, path: Path, category: str) -> FileEntry | None:
    try:
        rel = path.relative_to(root)
        stat = path.stat()
    except (OSError, ValueError):
        return None

    return FileEntry(
        id=_encode_id(root_key, rel),
        name=path.name,
        path=str(rel.as_posix()),
        category=category,
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        extension=path.suffix.lower().lstrip("."),
    )





def _scan_glob(
    out_root: Path,
    scan_dir: Path,
    root_key: str,
    pattern: str,
    category: str,
) -> list[FileEntry]:
    if not scan_dir.is_dir():
        return []
    entries: list[FileEntry] = []
    for path in sorted(scan_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file():
            entry = _entry_from_path(out_root, root_key, path, category)
            if entry:
                entries.append(entry)
    return entries





def _docx_category(name: str) -> str:
    if "отобранные" in name.lower():
        return "export_selected"
    return "export_word"


def list_files(settings: Settings, *, include_downloads: bool = True) -> list[FileEntry]:
    out = settings.output_dir.resolve()
    dirs = output_dirs(settings)
    entries: list[FileEntry] = []

    def add(entries_list: list[FileEntry]) -> None:
        for entry in entries_list:
            key = entry.path
            existing_idx = next((i for i, e in enumerate(entries) if e.path == key), None)
            if existing_idx is not None:
                continue
            # legacy: один и тот же файл в корне и в подпапке — оставляем подпапку
            dup_name_idx = next(
                (i for i, e in enumerate(entries) if e.name == entry.name), None
            )
            if dup_name_idx is not None:
                existing = entries[dup_name_idx]
                if "/" not in existing.path and "/" in entry.path:
                    entries[dup_name_idx] = entry
                continue
            entries.append(entry)

    add(_scan_glob(out, dirs["excel"], "output", "*.xlsx", "export_excel"))
    add(_scan_glob(out, out, "output", "*.xlsx", "export_excel"))
    add(_scan_glob(out, dirs["word"], "output", "*.docx", "export_word"))
    add(_scan_glob(out, dirs["selected"], "output", "*.docx", "export_selected"))
    for path in sorted(out.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        if "отобранные" in path.name.lower():
            if (dirs["selected"] / path.name).is_file():
                continue
            category = "export_selected"
        else:
            category = "export_word"
        entry = _entry_from_path(out, "output", path, category)
        if entry:
            add([entry])
    # JSON для веб-отбора — не показываем в списке выгрузок (только через раздел «Отбор»)

    if include_downloads:
        downloads = settings.downloads_dir.resolve()
        if downloads.is_dir():
            for path in sorted(downloads.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.is_file():
                    entry = _entry_from_path(downloads, "downloads", path, "download")
                    if entry:
                        entries.append(entry)

    return entries





def guess_media_type(path: Path) -> str:

    mime, _ = mimetypes.guess_type(str(path))

    if mime:

        return mime

    ext = path.suffix.lower()

    return {

        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",

        ".pdf": "application/pdf",

        ".html": "text/html; charset=utf-8",

        ".bin": "application/octet-stream",

    }.get(ext, "application/octet-stream")





def list_document_files(settings: Settings, files_path: str | None) -> list[FileEntry]:

    if not files_path:

        return []

    folder = Path(files_path)

    base = settings.downloads_dir.resolve()

    try:

        folder = folder.resolve()

    except OSError:

        return []

    if not str(folder).startswith(str(base)) or not folder.is_dir():

        return []

    rel_root = folder.relative_to(base)

    entries: list[FileEntry] = []

    for path in sorted(folder.iterdir()):

        if not path.is_file():

            continue

        rel = rel_root / path.name

        stat = path.stat()

        ext = path.suffix.lower().lstrip(".") or "bin"

        entries.append(

            FileEntry(

                id=_encode_id("downloads", rel),

                name=path.name,

                path=str(rel.as_posix()),

                category="document_attachment",

                size=stat.st_size,

                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),

                extension=ext,

            )

        )

    return entries


