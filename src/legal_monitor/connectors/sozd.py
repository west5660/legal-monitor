from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from urllib.parse import urlencode

import httpx

from legal_monitor.connectors.base import BaseConnector
from legal_monitor.utils import request_with_retries
from legal_monitor.models import RawDocument

logger = logging.getLogger(__name__)

SOZD_BASE = "https://sozd.duma.gov.ru"
SOZD_SEARCH = f"{SOZD_BASE}/oz/b"
BILL_NUMBER_RE = re.compile(r"(\d{5,7}-\d+)")
MAX_SEARCH_PAGES = 100
ENRICH_DELAY_SEC = 0.15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class SozdConnector(BaseConnector):
    name = "sozd"

    def __init__(self, use_playwright: bool = True, enrich_cards: bool = True):
        self.use_playwright = use_playwright
        self.enrich_cards = enrich_cards

    def fetch(self, date_from: date, date_to: date) -> list[RawDocument]:
        stubs = self._fetch_search_http(date_from, date_to)
        if not stubs and self.use_playwright:
            stubs = self._fetch_search_playwright(date_from, date_to)
        if not stubs:
            logger.warning("СОЗД: поиск не вернул законопроектов за %s — %s", date_from, date_to)
            return []

        if not self.enrich_cards:
            return [self._stub_to_raw(stub) for stub in stubs.values()]

        documents: list[RawDocument] = []
        skipped_no_date = 0
        headers = _http_headers()
        with httpx.Client(timeout=90.0, headers=headers, follow_redirects=True) as client:
            for idx, (number, stub) in enumerate(stubs.items(), start=1):
                if idx > 1:
                    time.sleep(ENRICH_DELAY_SEC)
                doc, no_date = self._enrich_bill(client, number, stub, date_from, date_to)
                if no_date:
                    skipped_no_date += 1
                if doc:
                    documents.append(doc)

        if skipped_no_date:
            logger.info(
                "СОЗД: пропущено %s законопроектов без распознанной даты регистрации",
                skipped_no_date,
            )
        logger.info("СОЗД: получено %s законопроектов (обогащено карточек: %s)", len(documents), len(stubs))
        return documents

    def _build_url(self, date_from: date, date_to: date, page: int = 1) -> str:
        params = {
            "date_period_from_Year": date_from.strftime("%d.%m.%Y"),
            "date_period_to_Year": date_to.strftime("%d.%m.%Y"),
            "b[Year]": f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}",
            "b[ClassOfTheObjectLawmakingId]": "1",
            "cond[ClassOfTheObjectLawmaking]": "any",
            "sort_by_34f6ae40-bdf0-408a-a56e-e48511c6b618": "RegisterDate",
            "direction_34f6ae40-bdf0-408a-a56e-e48511c6b618": "desc",
            "page": str(page),
        }
        return f"{SOZD_SEARCH}?{urlencode(params)}#data_source_tab_b"

    def _fetch_search_http(self, date_from: date, date_to: date) -> dict[str, dict]:
        stubs: dict[str, dict] = {}
        headers = _http_headers()

        with httpx.Client(timeout=90.0, headers=headers, follow_redirects=True) as client:
            for page_num in range(1, MAX_SEARCH_PAGES + 1):
                url = self._build_url(date_from, date_to, page_num)
                try:
                    response = request_with_retries(client, "GET", url)
                except Exception as exc:
                    logger.warning("СОЗД HTTP стр.%s: %s", page_num, exc)
                    break

                page_stubs = _parse_search_page(response.text)
                if not page_stubs:
                    break

                new_count = 0
                for number, stub in page_stubs.items():
                    if number not in stubs:
                        stubs[number] = stub
                        new_count += 1

                if new_count == 0:
                    break

        logger.info("СОЗД поиск (HTTP): %s законопроектов за %s — %s", len(stubs), date_from, date_to)
        return stubs

    def _fetch_search_playwright(self, date_from: date, date_to: date) -> dict[str, dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright не установлен. pip install playwright && playwright install chromium")
            return {}

        stubs: dict[str, dict] = {}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=USER_AGENT, locale="ru-RU")
                page = context.new_page()

                for page_num in range(1, MAX_SEARCH_PAGES + 1):
                    url = self._build_url(date_from, date_to, page_num)
                    page.goto(url, wait_until="networkidle", timeout=90000)
                    page.wait_for_timeout(1500)

                    html = page.content()
                    page_stubs = _parse_search_page(html)
                    if not page_stubs:
                        break

                    new_count = 0
                    for number, stub in page_stubs.items():
                        if number not in stubs:
                            stubs[number] = stub
                            new_count += 1
                    if new_count == 0:
                        break

                browser.close()
        except Exception as exc:
            logger.warning("СОЗД Playwright: %s", exc)

        logger.info("СОЗД поиск (Playwright): %s законопроектов", len(stubs))
        return stubs

    def _enrich_bill(
        self,
        client: httpx.Client,
        number: str,
        stub: dict,
        date_from: date,
        date_to: date,
    ) -> tuple[RawDocument | None, bool]:
        """Возвращает (документ или None, пропущен_ли_из-за_отсутствия_даты)."""
        url = stub.get("url") or f"{SOZD_BASE}/bill/{number}"
        try:
            response = request_with_retries(client, "GET", url)
        except Exception as exc:
            logger.debug("СОЗД карточка %s: %s", number, exc)
            return self._stub_to_raw(stub, number=number, url=url), False

        parsed = _parse_bill_page(response.text, number)
        register_date = stub.get("register_date") or parsed.get("register_date")
        if not register_date:
            # Раньше законопроект без даты проходил фильтр по периоду молча.
            logger.debug("СОЗД: законопроект %s без даты регистрации — пропущен", number)
            return None, True
        if register_date < date_from or register_date > date_to:
            return None, False

        title = parsed.get("title") or stub.get("title") or f"Законопроект {number}"
        text = parsed.get("text") or title
        return (
            RawDocument(
                source="sozd",
                external_id=number,
                title=title,
                doc_type="Законопроект",
                register_date=register_date,
                stage=parsed.get("stage") or stub.get("stage") or "",
                url=url,
                initiator=parsed.get("initiator") or "",
                text=text,
                file_urls=parsed.get("file_urls") or [],
            ),
            False,
        )

    def _stub_to_raw(self, stub: dict, *, number: str | None = None, url: str | None = None) -> RawDocument:
        bill_number = number or stub["number"]
        bill_url = url or stub.get("url") or f"{SOZD_BASE}/bill/{bill_number}"
        return RawDocument(
            source="sozd",
            external_id=bill_number,
            title=stub.get("title") or f"Законопроект {bill_number}",
            doc_type="Законопроект",
            register_date=stub.get("register_date"),
            stage=stub.get("stage") or "",
            url=bill_url,
        )


def _http_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }


def _parse_search_page(html: str) -> dict[str, dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    stubs: dict[str, dict] = {}

    for row in soup.select("table.table tbody tr, #data_source_tab_b table tbody tr, tr[data-number]"):
        link = row.select_one("a[href*='/bill/']")
        if not link:
            continue
        href = link.get("href") or ""
        number_match = BILL_NUMBER_RE.search(href) or BILL_NUMBER_RE.search(row.get_text(" ", strip=True))
        if not number_match:
            continue
        number = number_match.group(1)
        row_text = row.get_text(" ", strip=True)
        stubs[number] = {
            "number": number,
            "title": link.get_text(" ", strip=True) or f"Законопроект {number}",
            "url": href if href.startswith("http") else f"{SOZD_BASE}{href}",
            "register_date": _extract_date(row_text),
            "stage": _extract_stage_from_row(row_text),
        }

    if stubs:
        return stubs

    for link in soup.select("a[href*='/bill/']"):
        href = link.get("href") or ""
        number_match = BILL_NUMBER_RE.search(href)
        if not number_match:
            continue
        number = number_match.group(1)
        if number in stubs:
            continue
        parent = link.find_parent("tr")
        row_text = parent.get_text(" ", strip=True) if parent else link.get_text(" ", strip=True)
        stubs[number] = {
            "number": number,
            "title": link.get_text(" ", strip=True) or f"Законопроект {number}",
            "url": href if href.startswith("http") else f"{SOZD_BASE}{href}",
            "register_date": _extract_date(row_text),
            "stage": _extract_stage_from_row(row_text),
        }

    return stubs


def _parse_bill_page(html: str, number: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    title = _extract_bill_title(soup, number)
    stage = _extract_bill_stage(soup)
    register_date = _extract_register_date(soup, html)
    initiator = _extract_initiator(soup)
    file_urls = _extract_file_urls(soup)

    related_numbers = sorted(set(BILL_NUMBER_RE.findall(html)) - {number})
    text_parts = [title, stage, initiator]
    if related_numbers:
        text_parts.append("Связанные законопроекты пакета: " + ", ".join(related_numbers[:15]))
    page_text = soup.get_text("\n", strip=True)
    for line in page_text.split("\n"):
        low = line.lower()
        if any(k in low for k in ("комитет", "пояснительн", "пакет", "труд", "налог", "закуп")):
            if 10 < len(line) < 400:
                text_parts.append(line)

    text = "\n".join(dict.fromkeys(p for p in text_parts if p))
    return {
        "title": title,
        "stage": stage,
        "register_date": register_date,
        "initiator": initiator,
        "text": text[:12000],
        "file_urls": file_urls,
    }


def _extract_bill_title(soup, number: str) -> str:
    for tag in soup.find_all(["p", "span", "h2"]):
        text = tag.get_text(" ", strip=True)
        if len(text) < 25 or len(text) > 600:
            continue
        if text.startswith("Законопроект №"):
            continue
        if re.match(r"^О\b|^Об\b|^Об\b", text, re.I):
            return text

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        text = re.sub(r"Законопроект\s*№\s*\S+", "", text, flags=re.I).strip()
        text = re.sub(r"^[\uE000-\uF8FF\s]+", "", text)
        if len(text) > 15:
            return text

    return f"Законопроект {number}"


def _extract_bill_stage(soup) -> str:
    for node in soup.find_all(string=re.compile(r"На рассмотрении|Принят|Отклонён|Отозван|Утратил", re.I)):
        text = str(node).strip()
        if len(text) < 80:
            return text
    return ""


def _extract_register_date(soup, html: str) -> date | None:
    for el in soup.find_all(attrs={"title": True}):
        title_attr = el.get("title") or ""
        if "разместил" in title_attr.lower():
            parsed = _extract_date(title_attr)
            if parsed:
                return parsed

    for line in soup.get_text("\n", strip=True).split("\n"):
        low = line.lower()
        if "дата регистрации" in low or "зарегистрирован" in low:
            parsed = _extract_date(line)
            if parsed:
                return parsed

    return _extract_date(html[:50000])


def _extract_initiator(soup) -> str:
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "Субъект права законодательной инициативы" in text:
            parts = text.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()[:500]
    return ""


def _extract_file_urls(soup) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True).lower()
        if not href.startswith("/download/"):
            continue
        if not any(k in label for k in ("пояснительн", "текст", "законопроект", "пакет", "федеральн", "проект")):
            continue
        full = f"{SOZD_BASE}{href}"
        if full in seen:
            continue
        seen.add(full)
        urls.append(full)
        if len(urls) >= 5:
            break
    return urls


def _extract_stage_from_row(row_text: str) -> str:
    for stage in ("На рассмотрении", "Принят", "Отклонён", "Отозван"):
        if stage.lower() in row_text.lower():
            return stage
    return ""


def _extract_date(text: str) -> date | None:
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None
