"""`serve`'s non-loopback warning: the web API has no authentication on
any endpoint (it's a personal, local-only tool - see cli.py's `serve`
default, scripts/start_web.py, and web/app.py's CORS allowlist, all
hard-pinned to 127.0.0.1). `--host` still lets someone start it on a
non-loopback address, which would then expose every endpoint,
unauthenticated, to the local network. `_warn_if_non_loopback()` is a
defensive warning for that case - it doesn't block the start, since the
user confirmed this app is only ever run on localhost and does not want
an auth mechanism built for a scenario that doesn't occur in practice.
"""
from __future__ import annotations

from legal_monitor.cli import _warn_if_non_loopback, console


def _last_printed_text() -> str:
    assert console.printed, "expected console.print() to have been called"
    return " ".join(str(a) for a in console.printed[-1])


def test_loopback_ipv4_prints_no_warning():
    console.printed.clear()
    _warn_if_non_loopback("127.0.0.1")
    assert console.printed == []


def test_localhost_hostname_prints_no_warning():
    console.printed.clear()
    _warn_if_non_loopback("localhost")
    assert console.printed == []


def test_loopback_ipv6_prints_no_warning():
    console.printed.clear()
    _warn_if_non_loopback("::1")
    assert console.printed == []


def test_wildcard_host_prints_warning():
    console.printed.clear()
    _warn_if_non_loopback("0.0.0.0")
    text = _last_printed_text()
    assert "0.0.0.0" in text
    assert "localhost" in text


def test_lan_address_prints_warning():
    console.printed.clear()
    _warn_if_non_loopback("192.168.1.50")
    text = _last_printed_text()
    assert "192.168.1.50" in text


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
