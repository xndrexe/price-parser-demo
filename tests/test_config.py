"""Настройки из переменных окружения — без настоящего .env."""

from pathlib import Path

from pricewatch import config

KEYS = [
    "START_URL", "MAX_PAGES", "WORKERS", "DELAY", "DB_PATH", "EXCEL_PATH",
    "TG_TOKEN", "TG_CHAT_ID", "GSHEET_ID", "GOOGLE_CREDENTIALS",
]  # fmt: skip


def _clean(monkeypatch):
    # настоящий .env не читаем: подменяем загрузку и чистим окружение
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_defaults(monkeypatch):
    _clean(monkeypatch)
    s = config.load()
    assert s.max_pages == 0 and s.workers == 8 and s.delay == 0.2
    assert s.db_path == config.ROOT / "data" / "pricewatch.db"
    assert s.tg_token == "" and s.gsheet_id == ""


def test_values_from_env(monkeypatch, tmp_path):
    _clean(monkeypatch)
    monkeypatch.setenv("MAX_PAGES", "3")
    monkeypatch.setenv("WORKERS", "0")  # меньше одного потока не бывает
    monkeypatch.setenv("DELAY", "1.5")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("EXCEL_PATH", "rel/out.xlsx")
    s = config.load()
    assert (s.max_pages, s.workers, s.delay) == (3, 1, 1.5)
    assert s.db_path == tmp_path / "x.db"
    assert s.excel_path == config.ROOT / Path("rel/out.xlsx")
