"""Уведомления об изменениях в Telegram через Bot API."""

from __future__ import annotations

import html
import logging
import time
from collections.abc import Sequence

import requests

from .store import Change

LIMIT = 4000  # у Telegram потолок 4096 знаков на сообщение
MAX_LINES = 30  # больше — в чат идёт сводка, подробности в таблице
TITLE_CHARS = 200  # одно длинное название не должно вытолкнуть сообщение за потолок
URL_CHARS = 1000
RETRIES = 3

log = logging.getLogger("pricewatch")


def _line(c: Change) -> str:
    title = c.title if len(c.title) <= TITLE_CHARS else c.title[: TITLE_CHARS - 1] + "…"
    name = html.escape(title)
    if len(c.url) <= URL_CHARS:
        name = f'<a href="{html.escape(c.url)}">{name}</a>'
    match c.kind:
        case "price":
            arrow = "📉" if float(c.new) < float(c.old) else "📈"
            return f"{arrow} {name}: £{c.old} → £{c.new}"
        case "stock":
            if c.new == "0":
                return f"⛔ {name}: закончился (было {c.old} шт)"
            if c.old == "0":
                return f"✅ {name}: снова в наличии, {c.new} шт"
            return f"📦 {name}: остаток {c.old} → {c.new} шт"
        case "new":
            return f"🆕 {name}: новый товар, £{c.new}"
        case "gone":
            return f"❌ {name}: пропал с сайта"
        case "back":
            return f"↩️ {name}: снова на сайте, £{c.new}"
    return f"{name}: {c.kind}"


def format_changes(changes: Sequence[Change]) -> list[str]:
    """Тексты сообщений: по строке на изменение, длинный список — на несколько сообщений."""
    if not changes:
        return []
    head = f"<b>Изменения в каталоге: {len(changes)}</b>"
    lines = [_line(c) for c in changes[:MAX_LINES]]
    if len(changes) > MAX_LINES:
        lines.append(f"…и ещё {len(changes) - MAX_LINES} — полный список на листе «Изменения» таблицы.")
    messages, cur = [], head
    for line in lines:
        if len(cur) + 1 + len(line) > LIMIT:
            messages.append(cur)
            cur = line
        else:
            cur += "\n" + line
    messages.append(cur)
    return messages


def send_telegram(session: requests.Session, token: str, chat_id: str, text: str, pause: float = 2.0) -> None:
    """Отправка с повтором при перегрузке Telegram (429, 5xx) и обрыве связи; прочие ошибки — сразу."""
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
        except requests.ConnectionError:
            if attempt == RETRIES:
                raise
            time.sleep(pause * attempt)
            continue
        status = resp.status_code
        if (status == 429 or status >= 500) and attempt < RETRIES:
            wait = _retry_after(resp) or pause * attempt
            log.warning("telegram %s, retry in %.0fs", status, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return


def _retry_after(resp: requests.Response) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", 0)), 30.0)
    except ValueError:  # Retry-After бывает датой, а не числом секунд
        return 0.0
