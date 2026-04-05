#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Entry point
- Nhập nhiều Section (mỗi section: x0, coin, sell%)
- WebSocket ETH realtime từ Binance
- Beep + print khi giá chạm ngưỡng task
- Aggregate board BUY / SELL toàn bộ
"""

import asyncio
import json
import ssl
import sys
import threading
import time
import os
from typing import Optional

import certifi
import websockets

from task_manager import TaskManager, Section

# ── Beep ────────────────────────────────────────────────────────────
def beep(n: int = 1):
    """Cross-platform beep."""
    for _ in range(n):
        if sys.platform == "win32":
            import winsound
            winsound.Beep(880, 300)
        else:
            # macOS / Linux
            os.system("printf '\\a'")
        time.sleep(0.15)


# ── Globals ──────────────────────────────────────────────────────────
manager     = TaskManager()
current_eth = 0.0
_price_lock = threading.Lock()


# ── Input helpers ────────────────────────────────────────────────────
def get_float(prompt: str, min_val: float = None, max_val: float = None) -> float:
    while True:
        try:
            val = float(input(prompt).strip().replace(",", ""))
            if min_val is not None and val < min_val:
                print(f"  ⚠  Phải ≥ {min_val}"); continue
            if max_val is not None and val > max_val:
                print(f"  ⚠  Phải ≤ {max_val}"); continue
            return val
        except ValueError:
            print("  ⚠  Giá trị không hợp lệ.")


def input_section():
    """Nhập thông tin 1 section từ user, trả về Section hoặc None."""
    print("\n" + "─" * 60)
    print("  THÊM SECTION MỚI")
    print("─" * 60)

    label     = input("  Tên section (Enter để bỏ qua): ").strip()
    x0        = get_float("  Giá init x0 (USD)          : ", min_val=0.01)
    coin_init = get_float("  Số coin ban đầu             : ", min_val=0.0001)
    sell_pct  = get_float("  Tỉ lệ SELL mỗi lần (%)     : ", min_val=0.01, max_val=100)

    sec = manager.add_section(
        x0         = x0,
        coin_init  = coin_init,
        sell_ratio = sell_pct / 100.0,
        label      = label,
        force      = False,
    )

    if sec is None:
        retry = input("  Nhập lại với giá gợi ý? (y/n): ").strip().lower()
        if retry == "y":
            suggested = input("  Nhập giá gợi ý (USD)        : ").strip()
            try:
                x0_new = float(suggested.replace(",", ""))
                sec = manager.add_section(x0_new, coin_init, sell_pct / 100.0,
                                          label, force=True)
            except ValueError:
                print("  ⚠  Giá không hợp lệ.")
    return sec


# ── WebSocket ETH ────────────────────────────────────────────────────
async def watch_eth():
    global current_eth
    url = "wss://stream.binance.com:9443/stream?streams=ethusdt@miniTicker"
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    print("\n[WS] Đang kết nối Binance ETH stream...")
    reconnect_delay = 3

    while True:
        try:
            async with websockets.connect(url, ssl=ssl_ctx,
                                          ping_interval=20,
                                          ping_timeout=10) as ws:
                print("[WS] Kết nối thành công. Đang nhận giá ETH realtime...\n")
                reconnect_delay = 3
                async for raw in ws:
                    data    = json.loads(raw)
                    payload = data.get("data", data)
                    price_s = payload.get("c", "0")
                    try:
                        price = float(price_s)
                    except ValueError:
                        continue

                    with _price_lock:
                        current_eth = price

                    # Xử lý trigger
                    fired = manager.process_price(price)
                    if fired:
                        print(f"\n{'!'*60}")
                        for sec, task in fired:
                            print(f"  🔔 TRIGGER  ETH=${price:,.2f}  "
                                  f"Section {sec.id} '{sec.label}'  "
                                  f"#{task.id} [{task.direction}/{task.action}] "
                                  f"@ {task.target_pct:+.2f}%  ${task.target_price:,.2f}")
                        print(f"{'!'*60}")
                        beep(2 if any(t.action == "SELL" for _, t in fired) else 1)
                        manager.print_boards(price)

        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError) as e:
            print(f"[WS] Mất kết nối: {e}. Thử lại sau {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)


# ── Ticker display (mỗi 5s in giá + khoảng cách tới ngưỡng gần nhất) ──
async def ticker_display():
    await asyncio.sleep(3)  # chờ WS connect trước
    while True:
        await asyncio.sleep(5)
        with _price_lock:
            price = current_eth
        if price <= 0:
            continue

        pending = manager.all_pending_tasks()
        if not pending:
            continue

        # Tìm ngưỡng UP và DOWN gần nhất
        above = [t for t in pending if t.target_price > price]
        below = [t for t in pending if t.target_price <= price]
        nearest_up   = min(above, key=lambda t: t.target_price, default=None)
        nearest_down = max(below, key=lambda t: t.target_price, default=None)

        parts = [f"ETH=${price:,.2f}"]
        if nearest_up:
            d = (nearest_up.target_price - price) / price * 100
            parts.append(f"▲ #{nearest_up.id}[{nearest_up.action}]"
                         f"@${nearest_up.target_price:,.2f} ({d:+.2f}%)")
        if nearest_down:
            d = (nearest_down.target_price - price) / price * 100
            parts.append(f"▼ #{nearest_down.id}[{nearest_down.action}]"
                         f"@${nearest_down.target_price:,.2f} ({d:+.2f}%)")

        print("  │ " + "  ".join(parts))


# ── Interactive menu (chạy trong thread riêng) ───────────────────────
def menu_loop(loop: asyncio.AbstractEventLoop):
    """Chạy trong thread blocking — không block event loop."""
    time.sleep(1)  # chờ WS print welcome message
    while True:
        print("\n" + "═" * 60)
        print("  MENU")
        print("  1. Thêm section mới")
        print("  2. Xem board BUY / SELL")
        print("  3. Xem tất cả section")
        print("  4. Thoát")
        print("═" * 60)
        choice = input("  Chọn: ").strip()

        if choice == "1":
            input_section()
        elif choice == "2":
            with _price_lock:
                p = current_eth
            manager.print_boards(p if p > 0 else None)
        elif choice == "3":
            manager.print_boards(current_eth if current_eth > 0 else None)
        elif choice == "4":
            print("Thoát.")
            os._exit(0)
        else:
            print("  ⚠  Nhập 1–4.")


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("═" * 60)
    print("  COIN TASK MANAGER — ETH Realtime Monitor")
    print("═" * 60)

    # Nhập section đầu tiên trước khi start WS
    print("\nHãy thêm ít nhất 1 section để bắt đầu.")
    while not manager.sections:
        input_section()

    manager.print_boards()

    # Start menu thread
    t = threading.Thread(target=menu_loop,
                         args=(asyncio.get_event_loop(),),
                         daemon=True)
    t.start()

    # Start async tasks
    async def run_all():
        await asyncio.gather(
            watch_eth(),
            ticker_display(),
        )

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        print("\nĐã dừng.")


if __name__ == "__main__":
    main()
