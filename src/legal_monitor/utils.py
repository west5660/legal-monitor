from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSDATA_DIR = PROJECT_ROOT / "data" / "tessdata"
WINDOWS_TESSDATA_DIR = Path(r"C:\ProgramData\LegalMonitor\tessdata")
_tesseract_configured = False


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_filename(value: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"[^\w\-_.]", "_", value, flags=re.UNICODE)
    return cleaned[:max_len] or "document"


def download_file(url: str, dest: Path, timeout: float = 60.0) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            dest.write_bytes(response.content)
        return True
    except Exception:
        return False


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".pdf", ".bin"} or _looks_like_pdf(path):
        return _extract_pdf(path)
    if suffix in {".doc", ".docx"}:
        return _extract_docx(path)
    if suffix in {".txt", ".html", ".htm"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except Exception:
        return False


def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # pymupdf

        doc = fitz.open(path)
        parts: list[str] = []
        for page in doc:
            text = page.get_text().strip()
            if not text:
                text = _extract_pdf_page_ocr(page)
            if text:
                parts.append(text)
        doc.close()
        return "\n".join(parts).strip()
    except Exception:
        return ""


def _extract_pdf_page_ocr(page) -> str:
    """OCR для сканированных PDF (Tesseract + rus/eng)."""
    if not _ensure_tesseract_env():
        return ""
    tessdata = _get_tessdata_dir()
    try:
        textpage = page.get_textpage_ocr(
            language="rus+eng", full=True, dpi=150, tessdata=str(tessdata)
        )
        return page.get_text(textpage=textpage).strip()
    except Exception:
        try:
            textpage = page.get_textpage_ocr(
                language="rus", full=True, dpi=150, tessdata=str(tessdata)
            )
            return page.get_text(textpage=textpage).strip()
        except Exception:
            return ""


def _get_tessdata_dir() -> Path:
    env_dir = os.getenv("TESSDATA_DIR", "").strip()
    if env_dir:
        tessdata_dir = Path(env_dir)
        if not tessdata_dir.is_absolute():
            tessdata_dir = PROJECT_ROOT / tessdata_dir
    elif os.name == "nt" and (WINDOWS_TESSDATA_DIR / "rus.traineddata").is_file():
        tessdata_dir = WINDOWS_TESSDATA_DIR
    else:
        tessdata_dir = DEFAULT_TESSDATA_DIR
    _ensure_tessdata_files(tessdata_dir)
    return tessdata_dir


def _ensure_tessdata_files(target: Path) -> None:
    """Копирует rus/eng в ASCII-путь (Tesseract на Windows ломается на кириллице в пути)."""
    if (target / "rus.traineddata").is_file():
        return
    if os.name != "nt":
        return
    target.mkdir(parents=True, exist_ok=True)
    source = DEFAULT_TESSDATA_DIR if (DEFAULT_TESSDATA_DIR / "rus.traineddata").is_file() else None
    if source is None:
        system = Path(r"C:\Program Files\Tesseract-OCR\tessdata")
        if (system / "eng.traineddata").is_file():
            source = system
    if source is not None:
        for name in ("rus.traineddata", "eng.traineddata", "osd.traineddata"):
            src_file = source / name
            if src_file.is_file() and not (target / name).is_file():
                shutil.copy2(src_file, target / name)
    if not (target / "rus.traineddata").is_file():
        _download_tessdata_file(target / "rus.traineddata")
    if not (target / "eng.traineddata").is_file() and source is not None:
        src_eng = source / "eng.traineddata"
        if src_eng.is_file():
            shutil.copy2(src_eng, target / "eng.traineddata")


def _download_tessdata_file(dest: Path) -> None:
    url = f"https://github.com/tesseract-ocr/tessdata/raw/main/{dest.name}"
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
    except Exception:
        pass


def _ensure_tesseract_env() -> bool:
    """Настраивает PATH и TESSDATA_PREFIX для PyMuPDF OCR."""
    global _tesseract_configured
    if _tesseract_configured:
        return bool(shutil.which("tesseract"))

    candidates = [
        os.getenv("TESSERACT_CMD", "").strip(),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    tesseract_exe = next((p for p in candidates if p and Path(p).is_file()), None)
    if not tesseract_exe:
        tesseract_exe = shutil.which("tesseract")

    if tesseract_exe:
        tesseract_dir = str(Path(tesseract_exe).parent)
        os.environ["PATH"] = tesseract_dir + os.pathsep + os.environ.get("PATH", "")

    tessdata_dir = _get_tessdata_dir()
    if tessdata_dir.is_dir() and (tessdata_dir / "rus.traineddata").is_file():
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    elif tesseract_exe:
        system_prefix = Path(tesseract_exe).parent
        if (system_prefix / "tessdata").is_dir():
            os.environ["TESSDATA_PREFIX"] = str(system_prefix)

    _tesseract_configured = True
    return bool(shutil.which("tesseract") or tesseract_exe)


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""
