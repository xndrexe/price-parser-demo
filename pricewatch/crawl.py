"""Обход каталога: страницы списка по порядку, карточки товаров — в несколько потоков."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .parse import Product, parse_list, parse_product

log = logging.getLogger(__name__)

Fetch = Callable[[str], str]


@dataclass
class CrawlResult:
    products: list[Product] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages: int = 0
    complete: bool = False  # дошли до последней страницы без сбоев


def _product(fetch: Fetch, url: str) -> Product | str:
    try:
        return parse_product(fetch(url), url)
    except Exception as e:  # одна битая карточка не валит весь обход
        log.warning("product failed %s: %s", url, e)
        return f"{url}: {e}"


def crawl(fetch: Fetch, start_url: str, max_pages: int = 0, workers: int = 8) -> CrawlResult:
    res = CrawlResult()
    links: list[str] = []
    url: str | None = start_url
    visited: set[str] = set()
    while url and (not max_pages or res.pages < max_pages):
        if url in visited:
            # петля в «дальше» — вёрстка сломана; обход неполный, иначе непройденное станет «пропал с сайта»
            log.warning("list page loop at %s, stop", url)
            res.errors.append(f"{url}: next link loops back")
            break
        visited.add(url)
        try:
            page_links, url = parse_list(fetch(url), url)
        except Exception as e:  # сеть, 404 или сменилась вёрстка — дальше идти некуда
            log.warning("list page failed %s: %s", url, e)
            res.errors.append(f"{url}: {e}")
            break
        links.extend(page_links)
        res.pages += 1
    reached_end = url is None

    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item in pool.map(lambda u: _product(fetch, u), dict.fromkeys(links)):
            if isinstance(item, str):
                res.errors.append(item)
            elif item.upc not in seen:
                seen.add(item.upc)
                res.products.append(item)
    res.complete = reached_end and not res.errors
    return res
