"""Verifies the fix for the silent date-window bypass in the connectors.

Before this session's fix, a document whose publish/registration date could
not be parsed passed the date-range filter instead of being excluded - the
guard was `if date and (date < date_from or date > date_to): continue`,
which is false (and so does *not* skip the item) when date is None. That
bug was identical across pravo.py, regulation.py, duma.py and sozd.py.

These tests drive each connector's `fetch()` through a fake HTTP transport
(httpx.MockTransport - no real network) with a small fixture of items: one
in-window, one out-of-window, one with no parseable date at all. They assert
that only the in-window item survives.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from legal_monitor.connectors.pravo import PravoConnector
from legal_monitor.connectors.regulation import RegulationConnector
from legal_monitor.connectors.sozd import SozdConnector

DATE_FROM = date(2026, 9, 1)
DATE_TO = date(2026, 9, 14)


def test_pravo_excludes_items_without_parseable_date():
    payload = {
        "items": [
            {"eoNumber": "A1", "name": "В окне", "publishDateShort": "05.09.2026"},
            {"eoNumber": "A2", "name": "Вне окна", "publishDateShort": "01.01.2020"},
            {"eoNumber": "A3", "name": "Без даты"},  # no date field at all
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    import legal_monitor.connectors.pravo as pravo_module

    pravo_module.httpx.Client = client_factory
    try:
        docs = PravoConnector().fetch(DATE_FROM, DATE_TO)
    finally:
        pravo_module.httpx.Client = orig_client

    titles = {d.title for d in docs}
    assert titles == {"В окне"}, (
        "expected only the in-window, dated item to survive; "
        f"got {titles!r} (the undated item must NOT silently pass the filter)"
    )


def test_regulation_excludes_items_without_parseable_date():
    payload = {
        "data": [
            {"IDProject": "1", "Title": "В окне", "PublishDate": "2026-09-05"},
            {"IDProject": "2", "Title": "Без даты"},  # no PublishDate/Date/date field
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    import legal_monitor.connectors.regulation as regulation_module

    regulation_module.httpx.Client = client_factory
    try:
        docs = RegulationConnector().fetch(DATE_FROM, DATE_TO)
    finally:
        regulation_module.httpx.Client = orig_client

    titles = {d.title for d in docs}
    assert titles == {"В окне"}


SEARCH_PAGE_HTML = """
<table class="table"><tbody>
<tr><td><a href="/bill/111111-8">С датой в окне</a> 05.09.2026 На рассмотрении</td></tr>
<tr><td><a href="/bill/222222-8">Без даты в строке поиска</a> На рассмотрении</td></tr>
</tbody></table>
"""

BILL_PAGE_WITH_DATE = """
<html><body>
<h1>Законопроект № 111111-8</h1>
<p>О внесении изменений в некоторый закон Российской Федерации о чём-то важном</p>
</body></html>
"""

# No date anywhere findable: no title="...разместил..." attr, no "дата регистрации"
# text, and no dd.mm.yyyy-shaped substring anywhere in the page at all.
BILL_PAGE_NO_DATE = """
<html><body>
<h1>Законопроект № 222222-8</h1>
<p>Об изменении некоторого другого закона без единой даты на странице</p>
</body></html>
"""


def test_sozd_excludes_bill_without_parseable_date():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/oz/b" in url:
            return httpx.Response(200, text=SEARCH_PAGE_HTML)
        if "111111-8" in url:
            return httpx.Response(200, text=BILL_PAGE_WITH_DATE)
        if "222222-8" in url:
            return httpx.Response(200, text=BILL_PAGE_NO_DATE)
        return httpx.Response(404, text="")

    transport = httpx.MockTransport(handler)
    orig_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    import legal_monitor.connectors.sozd as sozd_module

    sozd_module.httpx.Client = client_factory
    try:
        docs = SozdConnector(use_playwright=False, enrich_cards=True).fetch(DATE_FROM, DATE_TO)
    finally:
        sozd_module.httpx.Client = orig_client

    numbers = {d.external_id for d in docs}
    assert numbers == {"111111-8"}, (
        f"expected only the dated bill to survive, got {numbers!r} - "
        "an undated bill must be excluded, not pass the period filter"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
