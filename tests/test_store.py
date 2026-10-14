from datetime import datetime

from pricewatch import store
from pricewatch.parse import Product


def prod(upc="a", price=10.0, stock=5, title="Книга"):
    return Product(upc, title, price, stock, 4, "Поэзия", f"https://shop.test/{upc}")


def kinds(changes):
    return sorted((c.upc, c.kind, c.old, c.new) for c in changes)


def test_first_run_saves_without_notifications(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    assert store.save_snapshot(conn, [prod("a"), prod("b")], complete=True) == []
    assert len(store.current(conn)) == 2


def test_price_stock_new_and_gone(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a"), prod("b"), prod("c")], complete=True)
    ch = store.save_snapshot(
        conn,
        [prod("a", price=8.5), prod("b", stock=0), prod("d", price=3)],
        complete=True,
        now=datetime(2026, 10, 15, 9, 0),
    )
    assert kinds(ch) == [
        ("a", "price", "10.00", "8.50"),
        ("b", "stock", "5", "0"),
        ("c", "gone", None, None),
        ("d", "new", None, "3.00"),
    ]
    assert {r["upc"] for r in store.current(conn)} == {"a", "b", "d"}
    assert len(store.recent_changes(conn)) == 4


def test_partial_crawl_does_not_mark_gone(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a"), prod("b")], complete=True)
    assert store.save_snapshot(conn, [prod("a")], complete=False) == []
    assert len(store.current(conn)) == 2


def test_gone_then_back(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a"), prod("b")], complete=True)
    store.save_snapshot(conn, [prod("a")], complete=True)
    ch = store.save_snapshot(conn, [prod("a"), prod("b", price=12)], complete=True)
    assert kinds(ch) == [("b", "back", None, "12.00"), ("b", "price", "10.00", "12.00")]


def test_unchanged_run_is_quiet(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a")], complete=True)
    assert store.save_snapshot(conn, [prod("a")], complete=True) == []
