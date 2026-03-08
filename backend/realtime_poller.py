"""
Background realtime price poller using Binance public API.
Crypto trades 24/7 — no trading-hours restriction.
"""
import logging
import random
import threading
import time

import requests

from .config import (
    BINANCE_BASE_URLS,
    CHECK_INTERVAL_SEC,
    REQUEST_TIMEOUT,
    SAMPLE_BTC_MAX,
    SAMPLE_BTC_MIN,
    SAMPLE_ETH_MAX,
    SAMPLE_ETH_MIN,
    SAMPLE_PRICES,
    SYMBOLS as DEFAULT_SYMBOLS,
)

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/1.0)", "Accept": "application/json"}

_lock = threading.Lock()
_latest_prices: dict[str, float] = {}
_poller_started = False


# Binance uses BTCUSDT, ETHUSDT. Map short names so "BTC"/"ETH" from UI work.
_BINANCE_SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}


def _binance_symbol(sym: str) -> str:
    s = sym.strip().upper()
    return _BINANCE_SYMBOL_MAP.get(s, s)


def _poll_once(symbols: list[str]) -> dict[str, float]:
    if SAMPLE_PRICES:
        result = {}
        for s in symbols:
            s = s.strip().upper()
            if s in ("BTCUSDT", "BTC"):
                result[s] = float(random.randint(SAMPLE_BTC_MIN, SAMPLE_BTC_MAX))
            elif s in ("ETHUSDT", "ETH"):
                result[s] = float(random.randint(SAMPLE_ETH_MIN, SAMPLE_ETH_MAX))
        return result

    prices = {}
    for sym in symbols:
        sym = sym.strip().upper()
        binance_sym = _binance_symbol(sym)
        last_status = None
        last_err = None
        for base in BINANCE_BASE_URLS:
            url = f"{base}/api/v3/ticker/price"
            try:
                r = requests.get(url, params={"symbol": binance_sym}, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                last_status = r.status_code
                if r.status_code == 451:
                    last_err = Exception(f"451 from {base}")
                    continue
                r.raise_for_status()
                data = r.json()
                prices[sym] = float(data["price"])
                last_err = None
                break
            except Exception as e:
                last_err = e
                continue
        if sym not in prices:
            # Keep warning concise; 451 is expected when the host is restricted.
            if last_status == 451:
                logger.warning("Binance blocked (451) for %s on this host. Try another region or set BINANCE_BASE_URLS.", binance_sym)
            else:
                logger.warning("Binance price fetch failed for %s: %s", binance_sym, last_err)
    return prices


def get_latest_prices() -> dict[str, float]:
    from .store import load_live_prices
    merged = load_live_prices()
    with _lock:
        merged.update(_latest_prices)
    return merged


def get_price(symbol: str) -> float | None:
    return get_latest_prices().get(symbol.strip().upper())


def poll_now() -> dict[str, float]:
    """Trigger immediate poll (manual action). Crypto is 24/7 so always runs."""
    from .store import load_all_task_engine_symbols, save_live_prices
    symbols = load_all_task_engine_symbols()
    if not symbols:
        symbols = DEFAULT_SYMBOLS
    if not symbols:
        return {}
    prices = _poll_once(symbols)
    if prices:
        with _lock:
            _latest_prices.update(prices)
        save_live_prices(prices)
        logger.info("poll_now: %s", ", ".join(f"{k}={v:,.2f}" for k, v in sorted(prices.items())))
    return prices


def _poll_loop():
    """Background loop: polls Binance API every CHECK_INTERVAL_SEC. Crypto is 24/7."""
    while True:
        try:
            from .store import load_all_task_engine_symbols
            symbols = load_all_task_engine_symbols()
            if not symbols:
                symbols = DEFAULT_SYMBOLS
            if symbols:
                prices = _poll_once(symbols)
                if prices:
                    with _lock:
                        _latest_prices.update(prices)
                    from .store import save_live_prices
                    save_live_prices(prices)
                    logger.info(
                        "Polled prices: %s",
                        ", ".join(f"{k}={v:,.2f}" for k, v in sorted(prices.items())),
                    )
                else:
                    logger.info("Poll returned no prices for %s", symbols)
        except Exception as e:
            logger.exception("Poller error: %s", e)
        time.sleep(CHECK_INTERVAL_SEC)


def start_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    mode = "SAMPLE" if SAMPLE_PRICES else "Binance"
    logger.info("Realtime poller started (every %ss, mode=%s)", CHECK_INTERVAL_SEC, mode)
