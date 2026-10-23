"""Загрузка страниц: повторы при сбоях, вежливая пауза, таймаут.

Здесь же проверка «тот же сайт» (same_site): по ней get_html не идёт по чужому
редиректу, а обход пропускает чужие ссылки.
"""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import LocationParseError
from urllib3.util import parse_url
from urllib3.util.retry import Retry

USER_AGENT = "Mozilla/5.0 (compatible; pricewatch-demo/1.0)"
MAX_REDIRECTS = 5
MAX_RETRY_AFTER = 60.0  # сек; дольше сайт не ждём, даже если просит


class _CappedRetry(Retry):
    """Retry-After сайта с потолком: заголовок на сутки иначе подвесил бы запуск на сутки."""

    def get_retry_after(self, response):
        after = super().get_retry_after(response)
        return None if after is None else min(after, MAX_RETRY_AFTER)


class Html(str):
    """Текст страницы и адрес, где она оказалась после редиректов: относительные
    ссылки разбираются от него, а не от запрошенного (/catalog → /catalog/)."""

    url: str

    def __new__(cls, text: str, url: str) -> Html:
        page = super().__new__(cls, text)
        page.url = url
        return page


class RedirectError(requests.RequestException):
    """Сайт перенаправил на чужой хост, на http вместо https или по кругу."""


def _site(url: str) -> tuple[str, str, int | None] | None:
    """Схема, хост без одной ведущей «www.» и порт — тем же разбором urllib3, которым
    адрес откроет requests. Адрес с логином или без хоста — None."""
    try:
        p = parse_url(url)
    except LocationParseError:  # порт не число или вне 0–65535
        return None
    # «\@» urlsplit читает как логин, а urllib3 режет хост на «\» — такой адрес не берём вовсе
    if not p.host or p.auth or "@" in urlsplit(url).netloc:
        return None
    return p.scheme, p.host.removeprefix("www."), p.port


def same_site(url: str, base: str) -> bool:
    """Только http(s) на тот же хост, что и base, и без отката с https на http:
    ссылка или редирект с сайта не уведёт во внутреннюю сеть, на чужой сайт
    или на открытый канал, где ответ можно подменить. Хост с «www.» и без неё
    считаем одним сайтом — многие магазины так перенаправляют; поддомен,
    другой порт, похожее имя и адрес с логином — чужой сайт."""
    u, b = _site(url), _site(base)
    if u is None or b is None or u[0] not in ("http", "https"):
        return False
    if b[0] == "https" and u[0] == "http":
        return False
    return u[1:] == b[1:]


def make_session(pool: int = 8) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = _CappedRetry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=pool)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_html(session: requests.Session, url: str, delay: float = 0.0) -> Html:
    # редиректы проходим сами: requests по умолчанию пошёл бы по Location куда угодно,
    # хоть на 169.254.169.254, и проверка ссылок в обходе ничего бы не дала
    for _ in range(MAX_REDIRECTS + 1):
        resp = session.get(url, timeout=20, allow_redirects=False)
        if not resp.is_redirect:
            break
        target = urljoin(url, resp.headers["location"])
        if not same_site(target, url):
            raise RedirectError(f"foreign redirect {url} -> {target}")
        url = target
    else:
        raise RedirectError(f"too many redirects from {url}")
    resp.raise_for_status()
    # Сервер не всегда называет кодировку — без этого «£» превращается в «Â£»
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    if delay:
        time.sleep(delay)
    return Html(resp.text, url)
