"""
Background checker: uses latest prices from realtime_poller,
checks if price would trigger any pending task in any section, and sends Telegram alert.

Crypto trades 24/7 — no trading-hours restriction.
READ-ONLY: does NOT modify engine state or section state.
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

# key: section_id → set of alerted task_ids
_alerted_tasks: dict[int, set[int]] = {}


def _check_section(section: dict, price: float, new_alerts_by_symbol: dict) -> None:
    """Check one section against the live price and collect new alerts."""
    section_id = section["id"]
    symbol = section["symbol"]
    x0 = section.get("x0", 0)
    if x0 <= 0:
        return

    current_pct = (price / x0 - 1.0) * 100.0

    from .store import load_task_queue_by_section
    tasks = load_task_queue_by_section(section_id)
    if not tasks:
        return

    alerted_set = _alerted_tasks.setdefault(section_id, set())
    still_in_band_ids: set[int] = set()
    section_new_alerts = []

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
                section_new_alerts.append((task, task_price, current_pct))
                alerted_set.add(task_id)

    # Reset dedup for tasks that left the band
    alerted_set -= (alerted_set - still_in_band_ids)

    if not section_new_alerts:
        return

    # Group by symbol for a single Telegram message per symbol
    bucket = new_alerts_by_symbol.setdefault(symbol, {
        "price": price,
        "sections": [],
    })
    bucket["sections"].append({
        "section": section,
        "current_pct": current_pct,
        "alerts": section_new_alerts,
    })


def run_check() -> None:
    """One-shot: read latest polled prices, check all sections, alert via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    from .realtime_poller import get_latest_prices
    from .store import load_sections

    prices = get_latest_prices()
    if not prices:
        return

    all_sections = load_sections()
    if not all_sections:
        return

    # Collect all alerts grouped by symbol
    new_alerts_by_symbol: dict[str, dict] = {}

    for section in all_sections:
        symbol = section["symbol"]
        price = prices.get(symbol)
        if price is None:
            continue
        try:
            _check_section(section, price, new_alerts_by_symbol)
        except Exception as e:
            logger.warning("Section %s check error: %s", section.get("id"), e)

    # Send one Telegram message per symbol
    for symbol, bucket in new_alerts_by_symbol.items():
        price = bucket["price"]
        lines = [f"🔔 Crypto Alert: {symbol}", f"Live price: {price:,.2f}", ""]

        for sec_entry in bucket["sections"]:
            sec = sec_entry["section"]
            current_pct = sec_entry["current_pct"]
            lines.append(
                f"📌 Section [{sec['name']}]  x0={sec['x0']:,.2f}  "
                f"pct={current_pct:+.4f}%"
            )
            for task, task_price, _ in sec_entry["alerts"]:
                action = task.get("action", "?")
                direction = task.get("direction", "?")
                target_pct = task.get("target_pct", 0)
                sell_origin = task.get("sell_origin", "")
                emoji = "🟢" if action == "BUY" else "🔴"
                origin_str = f" ← {sell_origin}" if sell_origin else ""
                lines.append(
                    f"  {emoji} {action}{origin_str} | {direction} "
                    f"target {target_pct:+.4f}% (price {task_price:,.2f})"
                )
                note = task.get("note", "")
                if note:
                    lines.append(f"     {note}")
            lines.append("")

        lines.append("⚠ Alert only — open app to execute.")

        msg = "\n".join(lines)
        total = sum(len(s["alerts"]) for s in bucket["sections"])
        if send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg):
            logger.info(
                "Telegram alert sent for %s (%d section(s), %d task(s))",
                symbol, len(bucket["sections"]), total,
            )
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
