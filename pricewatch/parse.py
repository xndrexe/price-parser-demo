"""Разбор страниц каталога. Чистые функции: HTML на входе, данные на выходе."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


class ParseError(ValueError):
    """Страница не похожа на ожидаемую — скорее всего, сайт поменял вёрстку."""


@dataclass(frozen=True)
class Product:
    upc: str
    title: str
    price: float
    stock: int
    rating: int
    category: str
    url: str


def parse_list(html: str, page_url: str) -> tuple[list[str], str | None]:
    """Ссылки на товары со страницы списка и адрес следующей страницы."""
    soup = BeautifulSoup(html, "lxml")
    pods = soup.select("article.product_pod h3 a[href]")
    if not pods:
        raise ParseError(f"no products on list page {page_url}")
    links = [urljoin(page_url, a["href"]) for a in pods]
    nxt = soup.select_one("li.next a[href]")
    return links, urljoin(page_url, nxt["href"]) if nxt else None


def _price(text: str) -> float:
    # Цифры вместе с разделителями: «£1,234.56», «€1.234,56», «12 345 ₽»
    m = re.search(r"\d(?:[\d.,\s]*\d)?", text)
    if not m:
        raise ParseError(f"bad price {text!r}")
    num = re.sub(r"\s", "", m.group())
    if "," in num and "." in num:
        # Дробная часть — после последнего разделителя, остальные делят тысячи
        dec = "." if num.rfind(".") > num.rfind(",") else ","
        num = num.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        sep = "," if "," in num else "."
        # «1,234» и «1.234.567» — тысячи; «51.77» и «12,5» — дробь
        if re.fullmatch(rf"\d{{1,3}}(?:\{sep}\d{{3}})+", num) and (sep == "," or num.count(".") > 1):
            num = num.replace(sep, "")
        else:
            num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        raise ParseError(f"bad price {text!r}") from None


def _stock(text: str) -> int:
    # «In stock (22 available)» → 22; «Out of stock» → 0
    if "out of stock" in text.lower():
        return 0
    m = re.search(r"\((\d+)", text)
    return int(m.group(1)) if m else 1


def parse_product(html: str, url: str) -> Product:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("div.product_main")
    if main is None or main.h1 is None:
        raise ParseError(f"no product card on {url}")
    info = {
        tr.th.get_text(strip=True): tr.td.get_text(strip=True)
        for tr in soup.select("table.table tr")
        if tr.th and tr.td
    }
    if "UPC" not in info:
        raise ParseError(f"no UPC on {url}")
    rating_tag = main.select_one("p.star-rating")
    rating_cls = next((c for c in (rating_tag.get("class", []) if rating_tag else []) if c in RATINGS), "")
    crumbs = soup.select("ul.breadcrumb li a")
    price_tag = main.select_one("p.price_color")
    return Product(
        upc=info["UPC"],
        title=main.h1.get_text(strip=True),
        price=_price(price_tag.get_text() if price_tag else info.get("Price (incl. tax)", "")),
        stock=_stock(info.get("Availability", "")),
        rating=RATINGS.get(rating_cls, 0),
        category=crumbs[-1].get_text(strip=True) if len(crumbs) >= 3 else "",
        url=url,
    )
