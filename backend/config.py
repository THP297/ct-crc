import os
from datetime import timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DEFAULT_SYMBOLS = "BTCUSDT, ETHUSDT"
SYMBOLS_STR = os.getenv("CRYPTO_SYMBOLS", DEFAULT_SYMBOLS)
SYMBOLS = [s.strip().upper() for s in SYMBOLS_STR.split(",") if s.strip()]

BINANCE_BASE_URL = os.getenv(
    "BINANCE_BASE_URL",
    "https://api.binance.com",
).strip().rstrip("/") or "https://api.binance.com"

# Binance publishes additional Spot API domains (api1..api4) for performance.
# Note: HTTP 451 from Binance usually means geo/legal restriction on the server IP.
_BINANCE_DEFAULT_BASE_URLS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]

BINANCE_BASE_URLS_STR = os.getenv("BINANCE_BASE_URLS", "").strip()
if BINANCE_BASE_URLS_STR:
    BINANCE_BASE_URLS = [
        u.strip().rstrip("/")
        for u in BINANCE_BASE_URLS_STR.split(",")
        if u.strip()
    ]
else:
    # Prefer configured BINANCE_BASE_URL first (backwards compatible)
    others = [u for u in _BINANCE_DEFAULT_BASE_URLS if u.rstrip("/") != BINANCE_BASE_URL]
    BINANCE_BASE_URLS = [BINANCE_BASE_URL] + others

SAMPLE_PRICES = os.getenv("SAMPLE_PRICES", "").strip().lower() in ("1", "true", "yes")

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0").strip() or "0.0.0.0"
FLASK_PORT = int(os.getenv("FLASK_PORT", "5004").strip() or "5004")

TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").strip().rstrip("/") or "https://api.telegram.org"

CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "30").strip() or "30")
PRICE_BAND_PCT = float(os.getenv("PRICE_BAND_PCT", "0.001").strip() or "0.001")
EQUAL_TOLERANCE_PCT = float(os.getenv("EQUAL_TOLERANCE_PCT", "0.0001").strip() or "0.0001")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "8").strip() or "8")
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "4096").strip() or "4096")

LOCAL_DATA_DIR_NAME = os.getenv("LOCAL_DATA_DIR", "local-data").strip() or "local-data"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


DATA_DIR = _project_root() / LOCAL_DATA_DIR_NAME

UTC_OFFSET_HOURS = int(os.getenv("UTC_OFFSET_HOURS", "7").strip() or "7")
UTC7 = timezone(timedelta(hours=UTC_OFFSET_HOURS))

SAMPLE_BTC_MIN = int(os.getenv("SAMPLE_BTC_MIN", "95000").strip() or "95000")
SAMPLE_BTC_MAX = int(os.getenv("SAMPLE_BTC_MAX", "100000").strip() or "100000")
SAMPLE_ETH_MIN = int(os.getenv("SAMPLE_ETH_MIN", "1800").strip() or "1800")
SAMPLE_ETH_MAX = int(os.getenv("SAMPLE_ETH_MAX", "2000").strip() or "2000")

SAMPLE_PRICES_ROTATE_MINUTES = int(os.getenv("SAMPLE_PRICES_ROTATE_MINUTES", "1").strip() or "1")
