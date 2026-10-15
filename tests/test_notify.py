import pytest

from pricewatch import notify
from pricewatch.store import Change


def ch(kind, old=None, new=None, title="Книга <1>", upc="a"):
    return Change("2026-10-15T09:00:00", upc, title, f"https://shop.test/{upc}?a=1&b=2", kind, old, new)


def test_lines_for_each_kind():
    text = notify.format_changes(
        [
            ch("price", "10.00", "8.50"),
            ch("price", "8.50", "9.00"),
            ch("stock", "5", "0"),
            ch("stock", "0", "3"),
            ch("stock", "5", "2"),
            ch("new", None, "3.00"),
            ch("gone"),
            ch("back", None, "4.00"),
        ]
    )[0]
    assert text.startswith("<b>Изменения в каталоге: 8</b>")
    for part in (
        "📉",
        "£10.00 → £8.50",
        "📈",
        "закончился (было 5 шт)",
        "снова в наличии, 3 шт",
        "остаток 5 → 2 шт",
        "новый товар, £3.00",
        "пропал с сайта",
        "снова на сайте, £4.00",
    ):
        assert part in text
    # название и адрес экранированы под HTML Telegram
    assert "Книга &lt;1&gt;" in text and "a=1&amp;b=2" in text


def test_nothing_to_send():
    assert notify.format_changes([]) == []


def test_long_list_is_capped_and_split():
    many = [ch("price", "10.00", "9.00", title="Т" * 300, upc=str(i)) for i in range(100)]
    msgs = notify.format_changes(many)
    assert all(len(m) <= notify.LIMIT for m in msgs)
    assert len(msgs) > 1
    assert "…и ещё 70" in msgs[-1]


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))

        class R:
            def raise_for_status(self):
                pass

        return R()


def test_send_telegram_payload():
    s = FakeSession()
    notify.send_telegram(s, "123:ABC", "42", "<b>hi</b>")
    url, body = s.calls[0]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert body["chat_id"] == "42" and body["parse_mode"] == "HTML"


def test_exactly_max_lines_has_no_tail():
    msgs = notify.format_changes([ch("gone", upc=str(i)) for i in range(notify.MAX_LINES)])
    text = "\n".join(msgs)
    assert "…и ещё" not in text
    assert text.count("пропал с сайта") == notify.MAX_LINES


def test_split_keeps_every_line_and_order():
    many = [ch("gone", title=f"T{i:02d}" + "x" * 400, upc=str(i)) for i in range(notify.MAX_LINES)]
    msgs = notify.format_changes(many)
    assert all(len(m) <= notify.LIMIT for m in msgs)
    joined = "\n".join(msgs)
    positions = [joined.index(f"T{i:02d}") for i in range(notify.MAX_LINES)]
    assert positions == sorted(positions)
    assert msgs[0].startswith("<b>Изменения в каталоге: 30</b>")


def test_unknown_kind_does_not_crash():
    assert "rating" in notify.format_changes([ch("rating", "3", "4")])[0]


def test_send_telegram_raises_on_http_error():
    class Bad(FakeSession):
        def post(self, url, json, timeout):
            class R:
                def raise_for_status(self):
                    raise OSError("401")

            return R()

    with pytest.raises(OSError):
        notify.send_telegram(Bad(), "t", "1", "x")


def test_huge_title_and_url_fit_one_message():
    c = Change("2026-10-15T09:00:00", "a", "Т" * 5000, "https://shop.test/" + "x" * 5000, "gone", None, None)
    (msg,) = notify.format_changes([c])
    assert len(msg) <= notify.LIMIT
    assert "…" in msg and "href" not in msg  # длинный адрес — без ссылки, название обрезано


class Flaky:
    """Отдаёт по очереди заданные коды ответа или исключения."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, json, timeout):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out

        class R:
            status_code = out
            headers = {"Retry-After": "1"}

            def raise_for_status(self):
                if out >= 400:
                    raise OSError(str(out))

        return R()


def test_send_retries_overload_and_connection(monkeypatch):
    waits = []
    monkeypatch.setattr(notify.time, "sleep", waits.append)
    s = Flaky(429, notify.requests.ConnectionError("reset"), 200)
    notify.send_telegram(s, "t", "1", "x")
    assert s.calls == 3 and waits == [1.0, 4.0]  # Retry-After, затем пауза × номер попытки


def test_send_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    s = Flaky(502, 502, 502)
    with pytest.raises(OSError):
        notify.send_telegram(s, "t", "1", "x")
    assert s.calls == notify.RETRIES


def test_send_does_not_retry_bad_token(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    s = Flaky(401)
    with pytest.raises(OSError):
        notify.send_telegram(s, "t", "1", "x")
    assert s.calls == 1
