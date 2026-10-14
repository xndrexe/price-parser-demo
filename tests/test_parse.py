import pytest

from pricewatch.parse import ParseError, parse_list, parse_product

BASE = "https://books.toscrape.com/catalogue/page-1.html"


def test_list_page_links_and_next(list_html):
    links, nxt = parse_list(list_html, BASE)
    assert len(links) == 20
    assert links[0] == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert nxt == "https://books.toscrape.com/catalogue/page-2.html"


def test_last_page_has_no_next(last_html):
    links, nxt = parse_list(last_html, "https://books.toscrape.com/catalogue/page-50.html")
    assert len(links) == 20
    assert nxt is None


def test_product_card(book_html):
    url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    p = parse_product(book_html, url)
    assert p.upc == "a897fe39b1053632"
    assert p.title == "A Light in the Attic"
    assert p.price == 51.77
    assert p.stock == 22
    assert p.rating == 3
    assert p.category == "Poetry"
    assert p.url == url


def test_out_of_stock(book_html):
    p = parse_product(book_html.replace("In stock (22 available)", "Out of stock"), "u")
    assert p.stock == 0


def test_changed_layout_is_an_error_not_empty_data():
    with pytest.raises(ParseError):
        parse_list("<html><body>Сайт на обслуживании</body></html>", BASE)
    with pytest.raises(ParseError):
        parse_product("<html><body><h1>Новый дизайн</h1></body></html>", "u")
