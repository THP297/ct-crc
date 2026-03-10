"""
Realtime price streamer using Binance WebSocket (miniTicker).
Falls back to REST API if WebSocket prices are unavailable.
Crypto trades 24/7 — no trading-hours restriction.
"""
import asyncio
import json
import logging
import random
import ssl
import threading
import time

import certifi
import requests
import websockets

from .config import (
    BINANCE_BASE_URLS,
    BINANCE_WS_URL,
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
_first_ws_price_logged = False

_SAVE_THROTTLE_SEC = 30
_last_save_ts: float = 0.0

_BINANCE_SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
_BINANCE_REVERSE_MAP = {v: k for k, v in _BINANCE_SYMBOL_MAP.items()}


def _binance_symbol(sym: str) -> str:
    s = sym.strip().upper()
    return _BINANCE_SYMBOL_MAP.get(s, s)


def _user_symbol(binance_sym: str) -> str:
    """Map BTCUSDT back to BTC if the user uses short names."""
    return _BINANCE_REVERSE_MAP.get(binance_sym, binance_sym)


def _build_ws_url(symbols: list[str]) -> str:
    streams = []
    for sym in symbols:
        bsym = _binance_symbol(sym).lower()
        streams.append(f"{bsym}@miniTicker")
    return f"{BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"


def _throttled_save(prices: dict[str, float]) -> None:
    global _last_save_ts
    now = time.time()
    if now - _last_save_ts < _SAVE_THROTTLE_SEC:
        return
    _last_save_ts = now
    try:
        from .store import save_live_prices
        save_live_prices(prices)
    except Exception as e:
        logger.warning("save_live_prices failed: %s", e)


# ── WebSocket streaming ──────────────────────────────────────────────────────

async def _ws_loop() -> None:
    """Connect to Binance WebSocket and stream prices. Auto-reconnect with backoff."""
    backoff = 1
    max_backoff = 60
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            from .store import load_all_task_engine_symbols, load_live_prices
            symbols = load_all_task_engine_symbols()
            if not symbols:
                symbols = DEFAULT_SYMBOLS
            all_syms = list(dict.fromkeys([s.strip().upper() for s in DEFAULT_SYMBOLS] + (symbols or [])))
            if not all_syms:
                await asyncio.sleep(5)
                continue

            with _lock:
                _latest_prices.update(load_live_prices() or {})

            url = _build_ws_url(all_syms)
            logger.info("WebSocket connecting: %s", url)

            async with websockets.connect(url, ssl=ssl_ctx, ping_interval=20, ping_timeout=10) as ws:
                backoff = 1
                logger.info("WebSocket connected — streaming %s", all_syms)

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        payload = data.get("data", data)
                        binance_sym = payload.get("s", "")
                        price_str = payload.get("c")
                        if not binance_sym or price_str is None:
                            continue

                        price = float(price_str)
                        user_sym = _user_symbol(binance_sym)

                        global _first_ws_price_logged
                        if not _first_ws_price_logged:
                            _first_ws_price_logged = True
                            logger.info("First WS price received: %s=%s", user_sym, price)

                        with _lock:
                            _latest_prices[user_sym] = price
                            if user_sym != binance_sym:
                                _latest_prices[binance_sym] = price

                        with _lock:
                            snapshot = dict(_latest_prices)
                        _throttled_save(snapshot)

                    except (json.JSONDecodeError, ValueError, KeyError) as e:
                        logger.debug("WS message parse error: %s", e)

        except asyncio.CancelledError:
            logger.info("WebSocket loop cancelled")
            return
        except Exception as e:
            logger.warning("WebSocket error (reconnect in %ds): %s", backoff, e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def _run_ws_in_thread() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_ws_loop())


# ── SAMPLE_PRICES mode (unchanged) ───────────────────────────────────────────

def _sample_loop() -> None:
    while True:
        from .store import load_all_task_engine_symbols, save_live_prices
        symbols = load_all_task_engine_symbols()
        if not symbols:
            symbols = DEFAULT_SYMBOLS
        prices = {}
        for s in (symbols or []):
            s = s.strip().upper()
            if s in ("BTCUSDT", "BTC"):
                prices[s] = float(random.randint(SAMPLE_BTC_MIN, SAMPLE_BTC_MAX))
            elif s in ("ETHUSDT", "ETH"):
                prices[s] = float(random.randint(SAMPLE_ETH_MIN, SAMPLE_ETH_MAX))
        if prices:
            with _lock:
                _latest_prices.update(prices)
            save_live_prices(prices)
            logger.info("Sample prices: %s", ", ".join(f"{k}={v:,.2f}" for k, v in sorted(prices.items())))
        time.sleep(CHECK_INTERVAL_SEC)


# ── REST fallback (single shot) ──────────────────────────────────────────────

def _rest_poll_once(symbols: list[str]) -> dict[str, float]:
    prices = {}
    for sym in symbols:
        sym = sym.strip().upper()
        binance_sym = _binance_symbol(sym)
        for base in BINANCE_BASE_URLS:
            url = f"{base}/api/v3/ticker/price"
            try:
                r = requests.get(url, params={"symbol": binance_sym}, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                if r.status_code in (451, 418):
                    continue
                r.raise_for_status()
                prices[sym] = float(r.json()["price"])
                break
            except Exception:
                continue
    return prices


# ── Public API (same interface as before) ─────────────────────────────────────

def get_latest_prices() -> dict[str, float]:
    from .store import load_live_prices
    merged = load_live_prices()
    with _lock:
        merged.update(_latest_prices)
    return merged


def get_price(symbol: str) -> float | None:
    return get_latest_prices().get(symbol.strip().upper())


def poll_now() -> dict[str, float]:
    """Return latest WebSocket prices. Falls back to persisted then REST if WS has no data yet."""
    with _lock:
        if _latest_prices:
            snapshot = dict(_latest_prices)
            try:
                from .store import save_live_prices
                save_live_prices(snapshot)
            except Exception:
                pass
            return snapshot

    from .store import load_all_task_engine_symbols, load_live_prices
    persisted = load_live_prices()
    if persisted:
        return persisted

    symbols = load_all_task_engine_symbols()
    if not symbols:
        symbols = DEFAULT_SYMBOLS
    if not symbols:
        return {}

    if SAMPLE_PRICES:
        prices = {}
        for s in symbols:
            s = s.strip().upper()
            if s in ("BTCUSDT", "BTC"):
                prices[s] = float(random.randint(SAMPLE_BTC_MIN, SAMPLE_BTC_MAX))
            elif s in ("ETHUSDT", "ETH"):
                prices[s] = float(random.randint(SAMPLE_ETH_MIN, SAMPLE_ETH_MAX))
        return prices

    logger.info("poll_now: WS prices empty, falling back to REST")
    prices = _rest_poll_once(symbols)
    if prices:
        with _lock:
            _latest_prices.update(prices)
        from .store import save_live_prices
        save_live_prices(prices)
    return prices


def start_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True

    if SAMPLE_PRICES:
        t = threading.Thread(target=_sample_loop, daemon=True)
        t.start()
        logger.info("Realtime poller started (SAMPLE mode, every %ss)", CHECK_INTERVAL_SEC)
    else:
        t = threading.Thread(target=_run_ws_in_thread, daemon=True)
        t.start()
        logger.info("Realtime poller started (WebSocket mode)")
