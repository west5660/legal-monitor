from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from legal_monitor.connectors.base import BaseConnector
from legal_monitor.utils import request_with_retries
from legal_monitor.models import RawDocument

logger = logging.getLogger(__name__)

API_BASE = "http://publication.pravo.gov.ru/api"


class PravoConnector(BaseConnector):
    name = "pravo"

    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        documents: list[RawDocument] = []
        page = 1
        max_pages = 100
        headers = {"User-Agent": "LegalMonitor/0.1"}

        with httpx.Client(timeout=60.0, headers=headers) as client:
            while page <= max_pages:
                params = {
                    "PublishDateFrom": date_from.strftime("%d.%m.%Y"),
                    "PublishDateTo": date_to.strftime("%d.%m.%Y"),
                    "PageSize": 100,
                    "Index": page,
                }
                try:
                    response = request_with_retries(
                        client, "GET", f"{API_BASE}/Documents", params=params
                    )
                    payload = response.json()
                except Exception as exc:
                    logger.warning("pravo.gov.ru: ошибка запроса стр.%s — %s", page, exc)
                    break

                items = _extract_items(payload)
                if not items:
                    break

                in_range = 0
                for item in items:
                    doc = _map_item(item)
                    if not doc:
                        continue
                    if doc.register_date and (doc.register_date < date_from or doc.register_date > date_to):
                        continue
                    documents.append(doc)
                    in_range += 1

                if len(items) < 100 or in_range == 0:
                    break
                page += 1

        logger.info("pravo.gov.ru: получено %s документов", len(documents))
        return documents


def _extract_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "Items", "documents", "Documents", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_publish_date(item: dict) -> date | None:
    """Дата публикации из актуальных полей API pravo.gov.ru."""
    for key in (
        "publishDateShort",
        "documentDate",
        "viewDate",
        "publishDate",
        "PublishDate",
        "signDate",
        "SignDate",
        "jdRegDate",
    ):
        parsed = _parse_date(item.get(key))
        if parsed:
            return parsed
    return None


def _map_item(item: dict) -> RawDocument | None:
    eo_number = str(item.get("eoNumber") or item.get("EONumber") or "")
    doc_id = eo_number or str(item.get("id") or item.get("Id") or "")
    title = item.get("name") or item.get("Name") or item.get("title") or ""
    if not doc_id or not title:
        return None

    pub_date = _extract_publish_date(item)
    doc_type = item.get("documentType") or item.get("DocumentType") or item.get("complexName") or "НПА"
    if eo_number:
        url = f"http://publication.pravo.gov.ru/Document/View/{eo_number}"
    else:
        url = item.get("documentUrl") or item.get("DocumentUrl") or ""
        if not url and doc_id:
            url = f"http://publication.pravo.gov.ru/Document/View/{doc_id}"

    text = item.get("text") or item.get("Text") or ""
    file_urls = []
    # PDF скачивается при LLM-анализе (document_content), не при массовом ingest

    return RawDocument(
        source="pravo",
        external_id=doc_id,
        title=title.strip(),
        doc_type=str(doc_type),
        register_date=pub_date,
        stage="Опубликован",
        url=url,
        initiator=str(item.get("signatoryAuthority") or item.get("SignatoryAuthority") or ""),
        text=text if isinstance(text, str) else "",
        file_urls=file_urls,
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None
