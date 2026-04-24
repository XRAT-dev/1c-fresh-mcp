# ============================================================
#  config.py — настройки коннектора к 1С:Fresh
#  Читаются из .env через python-dotenv.
# ============================================================
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    # dotenv опционален — переменные можно задать и системно
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = True) -> bool:
    v = _env(name, "").lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# ── Подключение ─────────────────────────────────────────────
BASE_URL = _env("FRESH_BASE_URL")
USERNAME = _env("FRESH_USERNAME", "odata.user")
PASSWORD = _env("FRESH_PASSWORD")

VERIFY_SSL = _env_bool("FRESH_VERIFY_SSL", True)
REQUEST_TIMEOUT = _env_int("FRESH_TIMEOUT", 30)

# Часовой пояс сервера 1С в часах от UTC (дата документа)
TZ_OFFSET_HOURS = _env_int("FRESH_TZ_OFFSET", 3)

# Ставка НДС по умолчанию: НДС22 / НДС20 / НДС10 / НДС7 / НДС5 / НДС0 / БезНДС
VAT_DEFAULT = _env("FRESH_VAT_DEFAULT", "НДС22")

# ── Для pdf_invoice (необязательно) ─────────────────────────
PDF_BANK = {
    "name": _env("PDF_BANK_NAME"),
    "bik": _env("PDF_BANK_BIK"),
    "corr_acc": _env("PDF_BANK_CORR_ACC"),
    "settlement_acc": _env("PDF_BANK_SETTLEMENT_ACC"),
}
PDF_SIGNER_TITLE = _env("PDF_SIGNER_TITLE", "Руководитель")
PDF_SIGNER_NAME = _env("PDF_SIGNER_NAME")
PDF_BANNER_PATH = _env("PDF_BANNER_PATH")


def assert_configured() -> None:
    """Падает с понятным сообщением, если обязательные переменные не заданы."""
    missing = []
    if not BASE_URL:
        missing.append("FRESH_BASE_URL")
    if not PASSWORD:
        missing.append("FRESH_PASSWORD")
    if missing:
        raise RuntimeError(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
            + ". Скопируй .env.example в .env и заполни."
        )
