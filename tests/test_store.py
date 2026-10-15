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


def test_back_without_other_changes(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a"), prod("b")], complete=True)
    store.save_snapshot(conn, [prod("a")], complete=True)
    assert kinds(store.save_snapshot(conn, [prod("a"), prod("b")], complete=True)) == [
        ("b", "back", None, "10.00")
    ]
    assert {r["upc"] for r in store.current(conn)} == {"a", "b"}


def test_gone_is_reported_once(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a"), prod("b")], complete=True)
    assert kinds(store.save_snapshot(conn, [prod("a")], complete=True)) == [("b", "gone", None, None)]
    assert store.save_snapshot(conn, [prod("a")], complete=True) == []


def test_tiny_float_noise_is_not_a_price_change(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a", price=0.1 + 0.2)], complete=True)
    assert store.save_snapshot(conn, [prod("a", price=0.3)], complete=True) == []


def test_new_product_on_partial_crawl_is_reported(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a")], complete=True)
    assert kinds(store.save_snapshot(conn, [prod("b", price=7)], complete=False)) == [
        ("b", "new", None, "7.00")
    ]


def test_title_update_is_saved_quietly(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a")], complete=True)
    assert store.save_snapshot(conn, [prod("a", title="Новое имя")], complete=True) == []
    assert store.current(conn)[0]["title"] == "Новое имя"


def test_changes_timestamp_and_history_order(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    store.save_snapshot(conn, [prod("a")], complete=True)
    store.save_snapshot(conn, [prod("a", price=9)], complete=True, now=datetime(2026, 1, 1, 8, 0))
    store.save_snapshot(conn, [prod("a", price=8)], complete=True, now=datetime(2026, 1, 2, 8, 0))
    hist = store.recent_changes(conn)
    assert [(r["ts"], r["new"]) for r in hist] == [
        ("2026-01-02T08:00:00", "8.00"),
        ("2026-01-01T08:00:00", "9.00"),
    ]
    assert len(store.recent_changes(conn, limit=1)) == 1


def test_current_is_sorted_by_category_and_title(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    items = [
        Product("1", "Б", 1, 1, 1, "Поэзия", "u1"),
        Product("2", "А", 1, 1, 1, "Поэзия", "u2"),
        Product("3", "В", 1, 1, 1, "Детективы", "u3"),
    ]
    store.save_snapshot(conn, items, complete=True)
    assert [r["upc"] for r in store.current(conn)] == ["3", "2", "1"]
