"""Загрузка страниц: повторы при сбоях, вежливая пауза, таймаут."""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "Mozilla/5.0 (compatible; pricewatch-demo/1.0)"
MAX_REDIRECTS = 5


class RedirectError(requests.RequestException):
    """Сайт перенаправил на чужой хост, на http вместо https или по кругу."""


def same_site(url: str, base: str) -> bool:
    """Только http(s) на тот же хост, что и base, и без отката с https на http:
    ссылка или редирект с сайта не уведёт во внутреннюю сеть, на чужой сайт
    или на открытый канал, где ответ можно подменить."""
    u, b = urlsplit(url), urlsplit(base)
    if u.scheme not in ("http", "https") or u.netloc.lower() != b.netloc.lower():
        return False
    return not (b.scheme == "https" and u.scheme == "http")


def make_session(pool: int = 8) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=pool)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_html(session: requests.Session, url: str, delay: float = 0.0) -> str:
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
    return resp.text
