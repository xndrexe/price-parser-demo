"""Снимки каталога в SQLite и поиск изменений цены и наличия между запусками."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .parse import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    upc TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    stock INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    category TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    gone INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    upc TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    kind TEXT NOT NULL,      -- price | stock | new | gone | back
    old TEXT,
    new TEXT
);
"""


@dataclass(frozen=True)
class Change:
    ts: str
    upc: str
    title: str
    url: str
    kind: str
    old: str | None = None
    new: str | None = None


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _fmt_price(v: float) -> str:
    return f"{v:.2f}"


def save_snapshot(
    conn: sqlite3.Connection, products: list[Product], complete: bool, now: datetime | None = None
) -> list[Change]:
    """Сохраняет снимок и возвращает изменения с прошлого запуска.

    Первый запуск — только сохранение, без «новых товаров» на весь каталог.
    «Пропал с сайта» ставим лишь после полного обхода: иначе сбой на середине
    выглядел бы как исчезновение половины каталога.
    """
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    old = {r["upc"]: r for r in conn.execute("SELECT * FROM products")}
    first_run = not old
    changes: list[Change] = []

    def add(upc: str, title: str, url: str, kind: str, o: str | None = None, n: str | None = None) -> None:
        changes.append(Change(ts, upc, title, url, kind, o, n))

    with conn:
        for p in products:
            prev = old.get(p.upc)
            if prev is None:
                if not first_run:
                    add(p.upc, p.title, p.url, "new", None, _fmt_price(p.price))
                conn.execute(
                    "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,0)",
                    (p.upc, p.title, p.price, p.stock, p.rating, p.category, p.url, ts, ts),
                )
                continue
            if prev["gone"]:
                add(p.upc, p.title, p.url, "back", None, _fmt_price(p.price))
            if round(prev["price"], 2) != round(p.price, 2):
                add(p.upc, p.title, p.url, "price", _fmt_price(prev["price"]), _fmt_price(p.price))
            if prev["stock"] != p.stock:
                add(p.upc, p.title, p.url, "stock", str(prev["stock"]), str(p.stock))
            conn.execute(
                "UPDATE products SET title=?, price=?, stock=?, rating=?, category=?, url=?,"
                " last_seen=?, gone=0 WHERE upc=?",
                (p.title, p.price, p.stock, p.rating, p.category, p.url, ts, p.upc),
            )
        if complete:
            seen = {p.upc for p in products}
            for upc, prev in old.items():
                if upc not in seen and not prev["gone"]:
                    add(upc, prev["title"], prev["url"], "gone")
                    conn.execute("UPDATE products SET gone=1 WHERE upc=?", (upc,))
        conn.executemany(
            "INSERT INTO changes (ts, upc, title, url, kind, old, new) VALUES (?,?,?,?,?,?,?)",
            [(c.ts, c.upc, c.title, c.url, c.kind, c.old, c.new) for c in changes],
        )
    return changes


def current(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM products WHERE gone=0 ORDER BY category, title"))


def recent_changes(conn: sqlite3.Connection, limit: int = 500) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM changes ORDER BY id DESC LIMIT ?", (limit,)))
