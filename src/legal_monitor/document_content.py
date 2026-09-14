from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from legal_monitor.config import Settings
from legal_monitor.models import Document, RawDocument
from legal_monitor.utils import content_hash, download_file, extract_text_from_file, safe_filename

logger = logging.getLogger(__name__)

PRAVO_API = "http://publication.pravo.gov.ru/api"
PRAVO_PDF = "http://publication.pravo.gov.ru/File/pdf"
SOZD_BASE = "https://sozd.duma.gov.ru"
_EO_NUMBER_RE = re.compile(r"^\d{10,}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_MIN_USEFUL_TEXT = 400


def text_is_insufficient(text: str | None, title: str | None) -> bool:
    body = (text or "").strip()
    if len(body) < _MIN_USEFUL_TEXT:
        return True
    title_clean = re.sub(r"\s+", " ", (title or "").strip().lower())
    body_clean = re.sub(r"\s+", " ", body.lower())
    if title_clean and body_clean == title_clean:
        return True
    if title_clean and len(body) < len(title or "") * 1.4 and title_clean in body_clean:
        return True
    return False


def text_quality_note(text: str, title: str | None) -> str:
    if not text_is_insufficient(text, title):
        return (
            "Полнота текста: достаточная. Извлеки из текста все конкретные изменения "
            "(цифры, ставки, сроки, статьи)."
        )
    if len((text or "").strip()) < 80:
        return (
            "Полнота текста: только название или метаданные. "
            "Не пиши «нужно изучить текст». Укажи, что в доступных данных содержание "
            "изменений не раскрыто, и перечисли только то, что видно из названия "
            "(статьи, кодексы, субъекты)."
        )
    return (
        "Полнота текста: частичная (краткое описание без полного текста акта). "
        "Опиши всё, что явно указано в тексте; не выдумывай цифры."
    )


def enrich_document_text(session, doc: Document, settings: Settings) -> bool:
    """Догружает полный текст/PDF для документа перед LLM-анализом."""
    if not text_is_insufficient(doc.text, doc.title):
        return False

    updated = False
    if doc.source == "pravo":
        updated = _enrich_pravo(doc, settings)
    elif doc.source == "sozd":
        updated = _enrich_sozd(doc, settings)
    elif doc.source == "regulation":
        updated = _enrich_regulation(doc)

    if updated:
        doc.content_hash = content_hash(doc.text or "")
        doc.updated_at = datetime.utcnow()
        session.flush()
        logger.info(
            "Текст обогащён (%s): «%s» — %s симв.",
            doc.source,
            (doc.title or "")[:50],
            len(doc.text or ""),
        )
    return updated


def _enrich_pravo(doc: Document, settings: Settings) -> bool:
    eo_number = _resolve_pravo_eo_number(doc)
    if not eo_number:
        logger.debug("pravo: не удалось определить eoNumber для %s", doc.external_id)
        return False

    folder = settings.downloads_dir / "pravo" / safe_filename(eo_number)
    pdf_path = folder / "document.pdf"
    folder.mkdir(parents=True, exist_ok=True)

    if not pdf_path.is_file():
        if not download_file(f"{PRAVO_PDF}/{eo_number}", pdf_path, timeout=120.0):
            return False

    extracted = extract_text_from_file(pdf_path)
    if not extracted or len(extracted.strip()) < 100:
        extracted = _fetch_pravo_document_meta(eo_number)

    if not extracted or len(extracted.strip()) < 50:
        logger.warning(
            "pravo: PDF без текстового слоя для %s (нужен Tesseract для OCR)",
            eo_number,
        )
        return False

    doc.files_path = str(folder)
    if not doc.url or _UUID_RE.match(doc.external_id or ""):
        doc.url = f"http://publication.pravo.gov.ru/Document/View/{eo_number}"
    if _UUID_RE.match(doc.external_id or ""):
        doc.external_id = eo_number
    doc.text = extracted
    return True


def _resolve_pravo_eo_number(doc: Document) -> str | None:
    eid = (doc.external_id or "").strip()
    if _EO_NUMBER_RE.match(eid):
        return eid

    url = doc.url or ""
    match = re.search(r"/Document/View/(\d{10,})", url, re.I)
    if match:
        return match.group(1)

    title = (doc.title or "").strip()
    if not title or len(title) < 15:
        return None

    date_from = doc.register_date
    date_to = doc.register_date
    if not date_from:
        return None

    params = {
        "Name": title[:120],
        "PublishDateFrom": date_from.strftime("%d.%m.%Y"),
        "PublishDateTo": date_to.strftime("%d.%m.%Y"),
        "PageSize": 10,
        "Index": 1,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{PRAVO_API}/Documents", params=params)
            response.raise_for_status()
            items = response.json().get("items") or []
        title_low = title.lower()
        for item in items:
            name = str(item.get("name") or item.get("title") or "").strip().lower()
            if name and (name in title_low or title_low in name):
                eo = str(item.get("eoNumber") or "")
                if _EO_NUMBER_RE.match(eo):
                    return eo
        if items:
            eo = str(items[0].get("eoNumber") or "")
            if _EO_NUMBER_RE.match(eo):
                return eo
    except Exception as exc:
        logger.debug("pravo: поиск eoNumber по названию: %s", exc)
    return None


def _fetch_pravo_document_meta(eo_number: str) -> str:
    """Метаданные документа из API (если PDF/OCR не дали текст)."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{PRAVO_API}/Document", params={"eoNumber": eo_number})
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.debug("pravo: метаданные %s: %s", eo_number, exc)
        return ""

    parts = [
        str(data.get("complexName") or ""),
        str(data.get("name") or data.get("title") or ""),
        str(data.get("number") or ""),
    ]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _enrich_sozd(doc: Document, settings: Settings) -> bool:
    from legal_monitor.connectors.sozd import SOZD_BASE, _http_headers, _parse_bill_page

    number = (doc.external_id or "").strip()
    if not number:
        return False

    url = doc.url or f"{SOZD_BASE}/bill/{number}"
    try:
        with httpx.Client(timeout=90.0, headers=_http_headers(), follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            parsed = _parse_bill_page(response.text, number)
    except Exception as exc:
        logger.debug("sozd: карточка %s: %s", number, exc)
        return False

    file_urls = parsed.get("file_urls") or []
    card_text = (parsed.get("text") or "").strip()
    pdf_text = ""

    if file_urls:
        raw = RawDocument(
            source="sozd",
            external_id=number,
            title=doc.title or "",
            file_urls=file_urls,
        )
        folder = _download_attachments(settings, raw)
        if folder:
            pdf_text = _read_folder_text(folder)
            doc.files_path = str(folder)

    combined = _merge_text_parts(card_text, pdf_text)
    if not combined:
        return False

    if parsed.get("title") and len(parsed["title"]) > len(doc.title or ""):
        doc.title = parsed["title"]
    if parsed.get("stage"):
        doc.stage = parsed["stage"]
    if parsed.get("initiator"):
        doc.initiator = parsed["initiator"]
    doc.text = combined
    return True


def _enrich_regulation(doc: Document) -> bool:
    """Расширяет текст метаданными из XML-списка (полный текст API закрыт)."""
    parts = [
        doc.title or "",
        f"Стадия: {doc.stage}" if doc.stage else "",
        f"Инициатор/ведомство: {doc.initiator}" if doc.initiator else "",
        doc.text or "",
    ]
    combined = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if len(combined) <= len((doc.text or "").strip()) + 50:
        return False
    doc.text = combined
    return True


def _download_attachments(settings: Settings, raw: RawDocument) -> Path | None:
    folder = settings.downloads_dir / raw.source / safe_filename(raw.external_id)
    folder.mkdir(parents=True, exist_ok=True)
    saved = 0
    for idx, file_url in enumerate(raw.file_urls[:5]):
        ext = Path(file_url.split("?")[0]).suffix or ".pdf"
        dest = folder / f"file_{idx}{ext}"
        if dest.is_file() or download_file(file_url, dest, timeout=120.0):
            saved += 1
    return folder if saved else None


def _read_folder_text(folder: Path) -> str:
    parts = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            extracted = extract_text_from_file(path)
            if extracted:
                parts.append(extracted)
    return "\n\n".join(parts).strip()


def _merge_text_parts(*chunks: str) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        parts.append(text)
    return "\n\n".join(parts)
