from __future__ import annotations

from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def list_html() -> str:
    return (FIX / "list_page.html").read_text(encoding="utf-8")


@pytest.fixture
def last_html() -> str:
    return (FIX / "list_last.html").read_text(encoding="utf-8")


@pytest.fixture
def book_html() -> str:
    return (FIX / "book.html").read_text(encoding="utf-8")


def make_book(upc: str, title: str, price: float, stock: int) -> str:
    """Карточка в вёрстке сайта, но со своими значениями — для обхода без сети."""
    html = (FIX / "book.html").read_text(encoding="utf-8")
    return (
        html.replace("a897fe39b1053632", upc)
        .replace("<h1>A Light in the Attic</h1>", f"<h1>{title}</h1>")
        .replace("£51.77", f"£{price:.2f}")
        .replace("In stock (22 available)", f"In stock ({stock} available)" if stock else "Out of stock")
    )


def make_list(links: list[str], next_href: str | None) -> str:
    pods = "".join(f'<article class="product_pod"><h3><a href="{h}">x</a></h3></article>' for h in links)
    nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
    return f"<html><body>{pods}<ul class='pager'>{nxt}</ul></body></html>"


class FakeSite:
    """Сайт из словаря адрес → HTML; отсутствующий адрес — ошибка, как 404."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.hits: list[str] = []

    def __call__(self, url: str) -> str:
        self.hits.append(url)
        if url not in self.pages:
            raise OSError(f"404 {url}")
        return self.pages[url]
