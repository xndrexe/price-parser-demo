"""Выгрузка в Google Таблицу без сети: подменяем gspread и смотрим, что ушло в листы."""

import sys
import types

from pricewatch import export, store
from pricewatch.parse import Product


class FakeWorksheet:
    def __init__(self, title):
        self.title, self.data, self.frozen, self.cleared = title, None, None, False

    def clear(self):
        self.cleared = True

    def update(self, values, value_input_option):
        self.data = values

    def freeze(self, rows):
        self.frozen = rows


class FakeBook:
    def __init__(self):
        self.sheets = {"Товары": FakeWorksheet("Товары")}

    def worksheet(self, title):
        if title not in self.sheets:
            raise NotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]


class NotFound(Exception):
    pass


def test_to_gsheet_fills_both_sheets(tmp_path, monkeypatch):
    book = FakeBook()
    calls = {}

    def service_account(filename):
        calls["creds"] = filename
        return types.SimpleNamespace(open_by_key=lambda key: calls.setdefault("key", key) and book)

    fake = types.SimpleNamespace(service_account=service_account, WorksheetNotFound=NotFound)
    monkeypatch.setitem(sys.modules, "gspread", fake)

    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [Product("a", "Книга", 10.0, 3, 4, "Поэзия", "https://shop.test/a")], True)
    store.save_snapshot(conn, [Product("a", "Книга", 9.0, 3, 4, "Поэзия", "https://shop.test/a")], True)
    export.to_gsheet(store.current(conn), store.recent_changes(conn), "SHEET123", "/keys/sa.json")

    assert calls == {"creds": "/keys/sa.json", "key": "SHEET123"}
    goods, hist = book.sheets["Товары"], book.sheets["Изменения"]  # второй лист создан
    assert goods.cleared and goods.frozen == 1
    assert goods.data[0] == export.PRODUCT_HEADERS and goods.data[1][:3] == ["Книга", "Поэзия", 9.0]
    assert hist.data[1][1:5] == ["Цена", "Книга", 10.0, 9.0]
