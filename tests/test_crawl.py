from conftest import FakeSite, make_book, make_list

from pricewatch.crawl import crawl

ROOT = "https://shop.test/catalogue/"


def site(n_pages: int = 2, per_page: int = 3) -> dict[str, str]:
    pages = {}
    for p in range(1, n_pages + 1):
        hrefs = [f"item-{p}-{i}/index.html" for i in range(per_page)]
        nxt = f"page-{p + 1}.html" if p < n_pages else None
        pages[f"{ROOT}page-{p}.html"] = make_list(hrefs, nxt)
        for i, h in enumerate(hrefs):
            pages[ROOT + h] = make_book(f"upc-{p}-{i}", f"Книга {p}-{i}", 10 + i, 5)
    return pages


def test_full_crawl_follows_pages():
    res = crawl(FakeSite(site()), ROOT + "page-1.html", workers=4)
    assert res.pages == 2
    assert len(res.products) == 6
    assert res.complete and not res.errors


def test_page_limit_is_not_complete():
    res = crawl(FakeSite(site(n_pages=3)), ROOT + "page-1.html", max_pages=2)
    assert res.pages == 2 and len(res.products) == 6
    assert not res.complete


def test_broken_card_is_skipped_and_reported():
    pages = site()
    del pages[ROOT + "item-2-1/index.html"]
    res = crawl(FakeSite(pages), ROOT + "page-1.html")
    assert len(res.products) == 5
    assert len(res.errors) == 1 and "item-2-1" in res.errors[0]
    assert not res.complete


def test_broken_list_page_stops_but_keeps_what_was_found():
    pages = site(n_pages=3)
    del pages[ROOT + "page-2.html"]
    res = crawl(FakeSite(pages), ROOT + "page-1.html")
    assert res.pages == 1 and len(res.products) == 3
    assert not res.complete


def test_next_link_loop_stops():
    """Последняя страница ссылается сама на себя — обход не должен зациклиться."""
    pages = site(n_pages=2)
    pages[ROOT + "page-2.html"] = make_list([f"item-2-{i}/index.html" for i in range(3)], "page-1.html")
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert res.pages == 2 and len(res.products) == 6
    assert fake.hits.count(ROOT + "page-1.html") == 1


def test_duplicate_links_and_upc_counted_once():
    pages = site(n_pages=1)
    # та же карточка дважды и вторая ссылка на тот же товар (UPC)
    pages[ROOT + "page-1.html"] = make_list(
        ["item-1-0/index.html", "item-1-0/index.html", "item-1-1/index.html", "alias/index.html"], None
    )
    pages[ROOT + "alias/index.html"] = make_book("upc-1-1", "Книга 1-1", 11, 5)
    fake = FakeSite(pages)
    res = crawl(fake, ROOT + "page-1.html")
    assert sorted(p.upc for p in res.products) == ["upc-1-0", "upc-1-1"]
    assert fake.hits.count(ROOT + "item-1-0/index.html") == 1
    assert res.complete


def test_dead_start_page():
    res = crawl(FakeSite({}), ROOT + "page-1.html")
    assert res.pages == 0 and res.products == [] and not res.complete
    assert len(res.errors) == 1
