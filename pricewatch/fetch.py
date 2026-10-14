"""Загрузка страниц: повторы при сбоях, вежливая пауза, таймаут."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "Mozilla/5.0 (compatible; pricewatch-demo/1.0)"


def make_session(pool: int = 8) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=pool)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_html(session: requests.Session, url: str, delay: float = 0.0) -> str:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    # Сервер не всегда называет кодировку — без этого «£» превращается в «Â£»
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    if delay:
        time.sleep(delay)
    return resp.text
