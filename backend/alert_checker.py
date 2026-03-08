"""
Background checker: uses latest prices from realtime_poller,
checks if price would trigger any pending task, and sends Telegram alert.

Crypto trades 24/7 — no trading-hours restriction.
READ-ONLY: does NOT modify engine state.
"""
import logging
import threading
import time

from .config import (
    CHECK_INTERVAL_SEC,
    PRICE_BAND_PCT,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from .telegram_send import send_telegram

logger = logging.getLogger(__name__)

_alerted_tasks: dict[str, set[int]] = {}


def run_check() -> None:
    """One-shot: read latest polled prices, check against pending tasks, alert via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    from .realtime_poller import get_latest_prices
    from .store import load_task_queue, load_task_engine_state, load_all_task_engine_symbols

    symbols = load_all_task_engine_symbols()
    if not symbols:
        return

    prices = get_latest_prices()
    if not prices:
        return

    for symbol in symbols:
        price = prices.get(symbol)
        if price is None:
            continue

        state = load_task_engine_state(symbol)
        if state is None:
            continue

        x0 = state["x0"]
        if x0 <= 0:
            continue

        current_pct = (price / x0 - 1.0) * 100.0
        tasks = load_task_queue(symbol)
        if not tasks:
            continue

        alerted_set = _alerted_tasks.setdefault(symbol, set())
        new_alerts = []
        still_in_band_ids = set()

        for task in tasks:
            task_id = task["id"]
            target_pct = task["target_pct"]
            task_price = x0 * (1 + target_pct / 100)

            low = task_price * (1 - PRICE_BAND_PCT)
            high = task_price * (1 + PRICE_BAND_PCT)
            in_band = low <= price <= high

            would_trigger = False
            if task["direction"] == "UP" and current_pct >= target_pct:
                would_trigger = True
            elif task["direction"] == "DOWN" and current_pct <= target_pct:
                would_trigger = True

            if in_band or would_trigger:
                still_in_band_ids.add(task_id)
                if task_id not in alerted_set:
                    new_alerts.append((task, task_price))
                    alerted_set.add(task_id)

        alerted_set -= (alerted_set - still_in_band_ids)

        if not new_alerts:
            continue

        lines = [f"🔔 Crypto Alert: {symbol}"]
        lines.append(f"Live price: {price:,.2f} | x0: {x0:,.2f} | pct: {current_pct:+.4f}%")
        lines.append("")

        for task, task_price in new_alerts:
            action = task.get("action", "?")
            direction = task.get("direction", "?")
            target_pct = task.get("target_pct", 0)
            emoji = "🟢" if action == "BUY" else "🔴"
            lines.append(
                f"{emoji} {action} | {direction} target {target_pct:+.4f}% "
                f"(price {task_price:,.2f})"
            )
            note = task.get("note", "")
            if note:
                lines.append(f"   {note}")

        lines.append("")
        lines.append("⚠ Alert only — open app to execute.")

        msg = "\n".join(lines)
        if send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg):
            logger.info("Telegram alert sent for %s (%d tasks)", symbol, len(new_alerts))
        else:
            logger.warning("Failed to send Telegram alert for %s", symbol)


def start_background_checker() -> None:
    from .realtime_poller import start_poller
    start_poller()

    def loop():
        time.sleep(5)
        while True:
            try:
                run_check()
            except Exception as e:
                logger.exception("Checker error: %s", e)
            time.sleep(CHECK_INTERVAL_SEC)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    logger.info("Alert checker started (every %ss)", CHECK_INTERVAL_SEC)
