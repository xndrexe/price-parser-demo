"""Загрузка страниц: кодировка, пауза, ошибки — на подменённой сессии, без сети."""

import pytest

from pricewatch import fetch


class FakeResp:
    def __init__(self, encoding, status=200):
        self.encoding, self.status = encoding, status
        self._raw = "£51.77".encode()

    def raise_for_status(self):
        if self.status >= 400:
            raise OSError(str(self.status))

    @property
    def text(self):
        return self._raw.decode(self.encoding)


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return self.resp


@pytest.mark.parametrize("encoding", [None, "ISO-8859-1", "utf-8"])
def test_pound_sign_survives(encoding):
    assert fetch.get_html(FakeSession(FakeResp(encoding)), "u") == "£51.77"


def test_declared_encoding_is_kept():
    resp = FakeResp("cp1252")
    fetch.get_html(FakeSession(resp), "u")
    assert resp.encoding == "cp1252"


def test_http_error_raises_and_has_timeout():
    s = FakeSession(FakeResp("utf-8", status=404))
    with pytest.raises(OSError):
        fetch.get_html(s, "https://shop.test/x")
    assert s.calls == [("https://shop.test/x", 20)]


def test_delay_sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch.time, "sleep", slept.append)
    fetch.get_html(FakeSession(FakeResp("utf-8")), "u", delay=0.5)
    fetch.get_html(FakeSession(FakeResp("utf-8")), "u")
    assert slept == [0.5]


def test_session_retries_and_user_agent():
    s = fetch.make_session(pool=3)
    assert s.headers["User-Agent"] == fetch.USER_AGENT
    adapter = s.get_adapter("https://shop.test/")
    assert adapter.max_retries.total == 3
    assert 503 in adapter.max_retries.status_forcelist
    assert adapter._pool_maxsize == 3
