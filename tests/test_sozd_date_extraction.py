"""_extract_register_date(): targeted unit tests for the fallback removed
this session. Before the fix it had a third, last-resort path - take the
first DD.MM.YYYY-shaped substring anywhere in the first 50000 characters
of raw HTML, with no check that it's actually the register date - which
could pick up an unrelated date from elsewhere on the page (a related
bill's citation, review-history entry, or markup/meta date) and silently
report it as the register date. That's worse than reporting no date at
all, since the connector's date-window filter already excludes (and
counts) documents with no date - a WRONG date instead sails through
silently. Now the function returns None rather than guess.
"""
from __future__ import annotations

from datetime import date

import pytest
from bs4 import BeautifulSoup

from legal_monitor.connectors.sozd import _extract_register_date


def test_finds_date_via_title_attribute():
    html = """
    <html><body>
    <span title="Пользователь разместил документ 05.09.2026 12:00">карточка</span>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _extract_register_date(soup, html) == date(2026, 9, 5)


def test_finds_date_via_registration_text_line():
    html = """
    <html><body>
    <p>Дата регистрации: 07.09.2026</p>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _extract_register_date(soup, html) == date(2026, 9, 7)


def test_returns_none_rather_than_guess_an_unrelated_date():
    """The regression this fix targets: a date-shaped substring exists
    on the page (in an unrelated citation), but neither targeted marker
    ("разместил" title attribute, "дата регистрации"/"зарегистрирован"
    text) is present anywhere - the function must not fall back to
    grabbing that unrelated date.
    """
    html = """
    <html><body>
    <h1>Законопроект № 222222-8</h1>
    <p>Пакетный законопроект, связан с 111111-8, внесённым 01.01.2020 в рамках другой инициативы.</p>
    <footer>&copy; 2005-2026 sozd.duma.gov.ru</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _extract_register_date(soup, html) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
