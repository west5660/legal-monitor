#!/usr/bin/env python3
"""Сравнение legal_monitor (httpx) vs Scrapy vs Scrapling."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PRAVO_API = "http://publication.pravo.gov.ru/api/Documents"
REGULATION_API = "https://regulation.gov.ru/api/npalist"
SOZD_SEARCH = "https://sozd.duma.gov.ru/oz/b"
BILL_RE = re.compile(r"(\d{5,7}-\d+)")
UA = "LegalMonitor-Benchmark/1.0"


@dataclass
class BenchResult:
    source: str
    engine: str
    ok: bool
    seconds: float
    items: int
    pages: int
    notes: str = ""


def parse_dates(s_from: str, s_to: str) -> tuple[date, date]:
    return date.fromisoformat(s_from), date.fromisoformat(s_to)


def default_window() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=14), today


def bench_legal_monitor(source: str, date_from: date, date_to: date) -> BenchResult:
    t0 = time.perf_counter()
    try:
        if source == "pravo":
            from legal_monitor.connectors.pravo import PravoConnector

            docs = PravoConnector().fetch(date_from, date_to)
            pages = max(1, (len(docs) + 99) // 100)
            return BenchResult("pravo", "legal_monitor", True, time.perf_counter() - t0, len(docs), pages)
        if source == "regulation":
            from legal_monitor.connectors.regulation import RegulationConnector

            docs = RegulationConnector().fetch(date_from, date_to)
            pages = max(1, (len(docs) + 99) // 100)
            return BenchResult("regulation", "legal_monitor", True, time.perf_counter() - t0, len(docs), pages)
        if source == "sozd":
            from legal_monitor.connectors.sozd import SozdConnector

            docs = SozdConnector(use_playwright=False, enrich_cards=False).fetch(date_from, date_to)
            return BenchResult("sozd", "legal_monitor", True, time.perf_counter() - t0, len(docs), 1, "search only")
    except Exception as exc:
        return BenchResult(source, "legal_monitor", False, time.perf_counter() - t0, 0, 0, str(exc)[:240])
    return BenchResult(source, "legal_monitor", False, 0, 0, 0, "unknown")


def _parse_regulation_body(text: str, content_type: str = "") -> list[dict[str, Any]]:
    from legal_monitor.connectors.regulation import _parse_response

    class _Resp:
        def __init__(self, body: str, ctype: str):
            self.headers = {"content-type": ctype}
            self.text = body

        def json(self):
            return json.loads(self.text)

    return _parse_response(_Resp(text, content_type))  # type: ignore[arg-type]


def bench_scrapling(source: str, date_from: date, date_to: date) -> BenchResult:
    from scrapling.fetchers import Fetcher

    t0 = time.perf_counter()
    items: list[Any] = []
    pages = 0
    try:
        if source == "pravo":
            page = 1
            while page <= 100:
                params = {
                    "PublishDateFrom": date_from.strftime("%d.%m.%Y"),
                    "PublishDateTo": date_to.strftime("%d.%m.%Y"),
                    "PageSize": 100,
                    "Index": page,
                }
                resp = Fetcher.get(PRAVO_API, params=params, headers={"User-Agent": UA}, timeout=60)
                pages += 1
                if resp.status != 200:
                    break
                payload = resp.json()
                batch = payload if isinstance(payload, list) else payload.get("items") or payload.get("Items") or []
                if not batch:
                    break
                items.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        elif source == "regulation":
            offset = 0
            while True:
                resp = Fetcher.get(
                    REGULATION_API,
                    params={"limit": 100, "offset": offset, "sort": "desc"},
                    headers={"User-Agent": UA, "Accept": "application/json, application/xml"},
                    timeout=60,
                )
                pages += 1
                if resp.status != 200:
                    break
                batch = _parse_regulation_body(resp.text, "application/xml")
                if not batch:
                    break
                items.extend(batch)
                if len(batch) < 100:
                    break
                offset += 100
        elif source == "sozd":
            params = {
                "date_period_from_Year": date_from.strftime("%d.%m.%Y"),
                "date_period_to_Year": date_to.strftime("%d.%m.%Y"),
                "b[Year]": f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}",
                "b[ClassOfTheObjectLawmakingId]": "1",
                "cond[ClassOfTheObjectLawmaking]": "any",
                "page": "1",
            }
            resp = Fetcher.get(
                f"{SOZD_SEARCH}?{urlencode(params)}",
                headers={"User-Agent": UA},
                stealthy_headers=True,
                impersonate="chrome",
                timeout=90,
            )
            pages = 1
            if resp.status == 200:
                items = list(set(BILL_RE.findall(resp.text)))
        return BenchResult(source, "scrapling", True, time.perf_counter() - t0, len(items), pages)
    except Exception as exc:
        return BenchResult(source, "scrapling", False, time.perf_counter() - t0, 0, pages, str(exc)[:240])


def bench_scrapy(source: str, date_from: date, date_to: date) -> BenchResult:
    """Scrapy в отдельном процессе (reactor нельзя перезапускать)."""
    import subprocess

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--scrapy-worker",
            source,
            date_from.isoformat(),
            date_to.isoformat(),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=600,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "scrapy worker failed")[:240]
        return BenchResult(source, "scrapy", False, elapsed, 0, 0, err)
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return BenchResult(source, "scrapy", True, elapsed, data["items"], data["pages"])


def scrapy_worker(source: str, date_from: date, date_to: date) -> dict[str, int]:
    import scrapy
    from scrapy.crawler import CrawlerProcess

    state = {"items": 0, "pages": 0}

    class BenchSpider(scrapy.Spider):
        name = "bench"

        custom_settings = {
            "LOG_ENABLED": False,
            "ROBOTSTXT_OBEY": False,
            "CONCURRENT_REQUESTS": 4,
            "DOWNLOAD_TIMEOUT": 90,
            "USER_AGENT": UA,
        }

        def start_requests(self):
            if source == "pravo":
                params = {
                    "PublishDateFrom": date_from.strftime("%d.%m.%Y"),
                    "PublishDateTo": date_to.strftime("%d.%m.%Y"),
                    "PageSize": 100,
                    "Index": 1,
                }
                yield scrapy.Request(f"{PRAVO_API}?{urlencode(params)}", callback=self.parse_pravo, meta={"page": 1})
            elif source == "regulation":
                yield scrapy.Request(
                    f"{REGULATION_API}?limit=100&offset=0&sort=desc",
                    callback=self.parse_regulation,
                    meta={"offset": 0},
                )
            elif source == "sozd":
                params = {
                    "date_period_from_Year": date_from.strftime("%d.%m.%Y"),
                    "date_period_to_Year": date_to.strftime("%d.%m.%Y"),
                    "b[Year]": f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}",
                    "b[ClassOfTheObjectLawmakingId]": "1",
                    "cond[ClassOfTheObjectLawmaking]": "any",
                    "page": "1",
                }
                yield scrapy.Request(f"{SOZD_SEARCH}?{urlencode(params)}", callback=self.parse_sozd)

        def parse_pravo(self, response):
            state["pages"] += 1
            payload = response.json()
            batch = payload if isinstance(payload, list) else payload.get("items") or payload.get("Items") or []
            state["items"] += len(batch)
            page = response.meta["page"]
            if len(batch) >= 100 and page < 100:
                nxt = page + 1
                params = {
                    "PublishDateFrom": date_from.strftime("%d.%m.%Y"),
                    "PublishDateTo": date_to.strftime("%d.%m.%Y"),
                    "PageSize": 100,
                    "Index": nxt,
                }
                yield scrapy.Request(
                    f"{PRAVO_API}?{urlencode(params)}", callback=self.parse_pravo, meta={"page": nxt}
                )

        def parse_regulation(self, response):
            state["pages"] += 1
            batch = _parse_regulation_body(response.text, response.headers.get("Content-Type", ""))
            state["items"] += len(batch)
            if len(batch) >= 100:
                offset = response.meta["offset"] + 100
                yield scrapy.Request(
                    f"{REGULATION_API}?limit=100&offset={offset}&sort=desc",
                    callback=self.parse_regulation,
                    meta={"offset": offset},
                )

        def parse_sozd(self, response):
            state["pages"] += 1
            state["items"] = len(set(BILL_RE.findall(response.text)))

    process = CrawlerProcess()
    process.crawl(BenchSpider)
    process.start()
    return state


def run_all(date_from: date, date_to: date) -> list[BenchResult]:
    results: list[BenchResult] = []
    engines = [
        ("legal_monitor", bench_legal_monitor),
        ("scrapy", bench_scrapy),
        ("scrapling", bench_scrapling),
    ]
    for source in ("pravo", "regulation", "sozd"):
        print(f"=== {source} ===")
        for name, fn in engines:
            try:
                r = fn(source, date_from, date_to)
            except Exception as exc:
                r = BenchResult(source, name, False, 0, 0, 0, str(exc)[:240])
            results.append(r)
            status = "OK" if r.ok else "FAIL"
            print(
                f"  {r.engine:14} {status:4}  {r.seconds:6.1f}s  "
                f"items={r.items:5}  pages={r.pages}  {r.notes}"
            )
        print()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrapy-worker", nargs=3, metavar=("SOURCE", "FROM", "TO"))
    parser.add_argument("--sozd-only", action="store_true", help="только sozd для быстрого теста")
    args = parser.parse_args()

    if args.scrapy_worker:
        source, s_from, s_to = args.scrapy_worker
        out = scrapy_worker(source, *parse_dates(s_from, s_to))
        print(json.dumps(out))
        return

    date_from, date_to = default_window()
    sources_note = "pravo, regulation, sozd"
    if args.sozd_only:
        # переопределим run_all ниже через фильтр
        pass

    print(f"Окно: {date_from} — {date_to}")
    print(f"Источники: {sources_note}\n")

    if args.sozd_only:
        results = []
        for fn in (bench_legal_monitor, bench_scrapy, bench_scrapling):
            r = fn("sozd", date_from, date_to)
            results.append(r)
            print(r)
    else:
        results = run_all(date_from, date_to)

    out = ROOT / "output" / "parser_benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()
