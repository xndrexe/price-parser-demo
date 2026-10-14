"""Настройки из .env — ключи и адреса вне кода."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    start_url: str
    max_pages: int  # 0 — все страницы каталога
    workers: int
    delay: float  # пауза между запросами одного потока, сек
    db_path: Path
    excel_path: Path
    tg_token: str
    tg_chat_id: str
    gsheet_id: str
    google_credentials: str


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load() -> Settings:
    load_dotenv(ROOT / ".env")
    env = os.environ.get
    return Settings(
        start_url=env("START_URL", "https://books.toscrape.com/catalogue/page-1.html"),
        max_pages=int(env("MAX_PAGES", "0")),
        workers=max(1, int(env("WORKERS", "8"))),
        delay=float(env("DELAY", "0.2")),
        db_path=_path(env("DB_PATH", "data/pricewatch.db")),
        excel_path=_path(env("EXCEL_PATH", "out/products.xlsx")),
        tg_token=env("TG_TOKEN", ""),
        tg_chat_id=env("TG_CHAT_ID", ""),
        gsheet_id=env("GSHEET_ID", ""),
        google_credentials=env("GOOGLE_CREDENTIALS", ""),
    )
