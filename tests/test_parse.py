import pytest

from pricewatch.parse import ParseError, _price, _stock, parse_list, parse_product

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


@pytest.mark.parametrize(
    "text, value",
    [
        ("£51.77", 51.77),
        ("Price: £12", 12.0),
        ("£1,234.56", 1234.56),  # тысячи через запятую
        ("€1.234,56", 1234.56),  # европейская запись
        ("1 234,50 ₽", 1234.5),  # тысячи через пробел
        ("12\xa0345 ₽", 12345.0),  # неразрывный пробел
        ("12,5 €", 12.5),
        ("$1,234", 1234.0),
        ("1.234.567 ₫", 1234567.0),
    ],
)
def test_price_formats(text, value):
    assert _price(text) == pytest.approx(value)


def test_price_without_digits_is_an_error():
    with pytest.raises(ParseError):
        _price("Цена по запросу")


@pytest.mark.parametrize(
    "text, stock",
    [("In stock (22 available)", 22), ("In stock (1 available)", 1), ("Out of stock", 0), ("In stock", 1)],
)
def test_stock_texts(text, stock):
    assert _stock(text) == stock


def test_card_without_rating_and_category(book_html):
    html = book_html.replace("star-rating Three", "star-rating").replace('class="breadcrumb"', 'class="x"')
    p = parse_product(html, "u")
    assert p.rating == 0 and p.category == ""


def test_card_without_upc_is_an_error(book_html):
    with pytest.raises(ParseError, match="UPC"):
        parse_product(book_html.replace("<th>UPC</th>", "<th>Code</th>"), "u")


def test_list_links_are_absolute_and_relative_to_page():
    html = '<article class="product_pod"><h3><a href="../book_1/index.html">x</a></h3></article>'
    links, nxt = parse_list(html, "https://shop.test/catalogue/category/page-1.html")
    assert links == ["https://shop.test/catalogue/book_1/index.html"]
    assert nxt is None


@pytest.mark.parametrize(
    "text, value",
    [
        ("£51.77 2 шт", 51.77),  # соседнее число не приклеивается к цене
        ("12 345 ₽ 3 шт", 12345.0),
        ("1 234 567,89 ₽", 1234567.89),
        ("£0.99", 0.99),
    ],
)
def test_price_ignores_neighbour_numbers(text, value):
    assert _price(text) == pytest.approx(value)


@pytest.mark.parametrize(
    "text, stock", [("In stock (1,234 available)", 1234), ("In stock (1 234 available)", 1234)]
)
def test_stock_with_thousands(text, stock):
    assert _stock(text) == stock


def test_price_from_table_when_no_price_tag(book_html):
    # нет цены в карточке — берём из таблицы характеристик
    html = book_html.replace('class="price_color"', 'class="nope"')
    assert parse_product(html, "u").price == pytest.approx(51.77)
