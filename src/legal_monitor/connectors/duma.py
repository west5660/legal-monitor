from __future__ import annotations

import logging
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import feedparser
import httpx

from legal_monitor.connectors.base import BaseConnector
from legal_monitor.utils import request_with_retries
from legal_monitor.models import RawDocument

logger = logging.getLogger(__name__)

RSS_TEMPLATE = "http://api.duma.gov.ru/api/search.rss"


class DumaRssConnector(BaseConnector):
    name = "duma_rss"

    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        params = {
            "registration_start": date_from.strftime("%d.%m.%Y"),
            "registration_end": date_to.strftime("%d.%m.%Y"),
        }
        url = RSS_TEMPLATE
        documents: list[RawDocument] = []

        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                response = request_with_retries(client, "GET", url, params=params)
                content = response.content
        except Exception as exc:
            logger.warning("duma RSS: %s", exc)
            return []

        feed = feedparser.parse(content)
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            pub = entry.get("published") or entry.get("updated")
            register_date = None
            if pub:
                try:
                    register_date = parsedate_to_datetime(pub).date()
                except Exception:
                    register_date = None

            if register_date and (register_date < date_from or register_date > date_to):
                continue

            external_id = _extract_bill_number(title, link)
            documents.append(
                RawDocument(
                    source="duma_rss",
                    external_id=external_id,
                    title=title,
                    doc_type="Законопроект",
                    register_date=register_date,
                    stage="",
                    url=link,
                    initiator="",
                )
            )

        logger.info("duma RSS: получено %s законопроектов", len(documents))
        return documents


class DumaApiConnector(BaseConnector):
    name = "duma_api"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        if not self.api_key:
            logger.info("duma API: ключ не задан, пропуск")
            return []

        documents: list[RawDocument] = []
        page = 1
        base = "http://api.duma.gov.ru/api/search.bills.json"

        with httpx.Client(timeout=60.0) as client:
            while True:
                params = {
                    "apikey": self.api_key,
                    "registration_start": date_from.strftime("%d.%m.%Y"),
                    "registration_end": date_to.strftime("%d.%m.%Y"),
                    "page": page,
                    "limit": 100,
                }
                try:
                    response = request_with_retries(client, "GET", base, params=params)
                    payload = response.json()
                except Exception as exc:
                    logger.warning("duma API: %s", exc)
                    break

                items = payload if isinstance(payload, list) else payload.get("bills", [])
                if not items:
                    break

                for item in items:
                    number = str(item.get("number") or item.get("id") or "")
                    title = item.get("name") or item.get("title") or ""
                    if not number or not title:
                        continue
                    reg = item.get("registration_date") or item.get("registrationDate")
                    documents.append(
                        RawDocument(
                            source="duma_api",
                            external_id=number,
                            title=title,
                            doc_type="Законопроект",
                            register_date=_parse_api_date(reg),
                            stage=str(item.get("last_event") or item.get("stage") or ""),
                            url=item.get("url") or f"https://sozd.duma.gov.ru/bill/{number}",
                            initiator=str(item.get("initiator") or ""),
                        )
                    )

                if len(items) < 100:
                    break
                page += 1

        logger.info("duma API: получено %s законопроектов", len(documents))
        return documents


def _extract_bill_number(title: str, link: str) -> str:
    match = re.search(r"(\d{5,7}-\d+)", title) or re.search(r"(\d{5,7}-\d+)", link)
    if match:
        return match.group(1)
    return link or title[:100]


def _parse_api_date(value) -> date | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None
