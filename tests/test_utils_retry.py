"""request_with_retries(): added this session so a single transient network
failure (the WinError 10060 the user hit) doesn't zero out an entire
connector run. Verifies it retries the configured number of times, backs
off between attempts, returns on the first success, and still raises once
every attempt is exhausted (so a genuinely-down source is still reported,
not silently swallowed).
"""
from __future__ import annotations

import httpx
import pytest

from legal_monitor.utils import request_with_retries


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)


class _FlakyClient:
    """Fails `fail_times` times, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ConnectError("connection refused")
        return _FakeResponse(200)


class _AlwaysFailsClient:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        raise httpx.ConnectTimeout("timed out")


def test_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr("legal_monitor.utils.time.sleep", lambda _s: None)
    client = _FlakyClient(fail_times=2)
    response = request_with_retries(client, "GET", "http://example.test", attempts=3)
    assert response.status_code == 200
    assert client.calls == 3, "should have retried twice before succeeding on the 3rd call"


def test_raises_after_exhausting_all_attempts(monkeypatch):
    monkeypatch.setattr("legal_monitor.utils.time.sleep", lambda _s: None)
    client = _AlwaysFailsClient()
    with pytest.raises(httpx.ConnectTimeout):
        request_with_retries(client, "GET", "http://example.test", attempts=3)
    assert client.calls == 3, "a permanently-down source must still surface as an error, not vanish"


def test_no_retry_needed_on_first_success(monkeypatch):
    monkeypatch.setattr("legal_monitor.utils.time.sleep", lambda _s: (_ for _ in ()).throw(
        AssertionError("sleep should never be called when the first attempt succeeds")
    ))
    client = _FlakyClient(fail_times=0)
    request_with_retries(client, "GET", "http://example.test", attempts=3)
    assert client.calls == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
