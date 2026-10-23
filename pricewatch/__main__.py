"""Запуск: python -m pricewatch [--every 60] [--pages N]."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, replace

import requests

from . import config, export, notify, store
from .crawl import crawl
from .fetch import get_html, make_session

log = logging.getLogger("pricewatch")


class Redact(logging.Filter):
    """Вычищает секрет из всех записей журнала, включая чужие (urllib3 пишет адрес с токеном
    бота при повторе запроса) и текст трассировки."""

    def __init__(self, secret: str):
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secret:
            return True
        record.msg = record.getMessage().replace(self.secret, "***")
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = record.exc_text.replace(self.secret, "***")
        return True


@dataclass
class RunReport:
    products: int
    changes: int
    errors: int
    complete: bool


def run_once(cfg: config.Settings, session: requests.Session | None = None) -> RunReport:
    session = session or make_session(cfg.workers)
    started = time.monotonic()
    res = crawl(lambda u: get_html(session, u, cfg.delay), cfg.start_url, cfg.max_pages, cfg.workers)
    log.info(
        "crawled %d pages, %d products, %d errors in %.0fs",
        res.pages,
        len(res.products),
        len(res.errors),
        time.monotonic() - started,
    )
    if not res.products:
        # Сайт лёг или сменил вёрстку: старую таблицу не затираем пустой
        raise RuntimeError(f"nothing parsed, first error: {res.errors[:1]}")

    conn = store.connect(cfg.db_path)
    try:
        changes = store.save_snapshot(conn, res.products, res.complete)
        # уведомление обещает полный список на листе — изменения этого прохода не режем
        history = store.recent_changes(conn, max(store.HISTORY_ROWS, len(changes)))
        products = store.current(conn)
    finally:
        conn.close()

    try:
        export.to_excel(products, history, cfg.excel_path)
        log.info("excel saved: %s", cfg.excel_path)
    except OSError as e:
        # На Windows открытый в Excel файл не даёт себя заменить. Изменения уже в базе:
        # упасть здесь — значит потерять уведомление о них насовсем
        log.warning("excel save failed, will retry next run: %s", e)
    if cfg.gsheet_id and cfg.google_credentials:
        try:
            export.to_gsheet(products, history, cfg.gsheet_id, cfg.google_credentials)
            log.info("google sheet updated")
        except Exception as e:  # сеть, квота, ключ — как и с Excel, уведомление важнее таблицы
            log.warning("google sheet update failed, will retry next run: %s", e)

    if changes and cfg.tg_token and cfg.tg_chat_id:
        messages = notify.format_changes(changes)
        failed = 0
        for text in messages:
            try:
                notify.send_telegram(session, cfg.tg_token, cfg.tg_chat_id, text)
            except Exception as e:  # изменения уже в базе и на листе «Изменения» — там их и увидят
                failed += 1
                # в тексте ошибки requests — адрес вместе с токеном бота
                log.warning("telegram send failed: %s", str(e).replace(cfg.tg_token, "***"))
        log.info(
            "telegram: %d changes, %d of %d messages sent",
            len(changes),
            len(messages) - failed,
            len(messages),
        )
    return RunReport(len(res.products), len(changes), len(res.errors), res.complete)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pricewatch", description="Парсер каталога с выгрузкой в таблицу")
    ap.add_argument("--every", type=int, default=0, metavar="MIN", help="повторять каждые MIN минут")
    ap.add_argument("--pages", type=int, default=None, help="сколько страниц списка обойти (0 — все)")
    args = ap.parse_args(argv)
    if args.every < 0 or (args.pages is not None and args.pages < 0):
        ap.error("--every и --pages не могут быть отрицательными")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = config.load()
    if args.pages is not None:
        cfg = replace(cfg, max_pages=args.pages)
    for handler in logging.getLogger().handlers:
        handler.addFilter(Redact(cfg.tg_token))
    while True:
        try:
            r = run_once(cfg)
            log.info("done: %d products, %d changes, %d errors", r.products, r.changes, r.errors)
        except Exception:
            if not args.every:
                raise
            log.exception("run failed, next try in %d min", args.every)
        if not args.every:
            return
        time.sleep(args.every * 60)


if __name__ == "__main__":
    main()
