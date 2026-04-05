#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coin Simulator — dựa trên TaskEngine spawn logic
Simulate SELL/BUY theo ngưỡng % từ giá gốc đến giá mục tiêu

Quy tắc làm tròn:
  - Số coin SELL/BUY luôn làm tròn xuống 4 chữ số thập phân (floor)
  - Tránh bán/mua nhiều hơn thực tế cho phép
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

# ─────────────────────────────────────────────
# SPAWN RULES (giống TaskEngine gốc)
#   SEED      : DOWN SELL @ -2%   ↔  UP SELL @ +3%
#   SELL DOWN : → DOWN BUY  @ base-3%  (no sibling)
#               → DOWN SELL @ base-2%  ↔  UP SELL @ base+3%
#   SELL UP   : → DOWN BUY  @ base-2.5% (no sibling)
#               → DOWN SELL @ base-2%   ↔  UP SELL @ base+3%
#   BUY       : không spawn gì
# ─────────────────────────────────────────────

SELL_DOWN_OFFSET  = -2.0
SELL_UP_OFFSET    = +3.0
BUY_AFTER_DOWN    = -3.0
BUY_AFTER_UP      = -2.5
RESPAWN_DOWN_SELL = -2.0
RESPAWN_UP_SELL   = +3.0

COIN_DECIMALS = 4   # 0.0000


def floor4(x: float) -> float:
    """Làm tròn xuống 4 chữ số thập phân."""
    return math.floor(x * 10**COIN_DECIMALS) / 10**COIN_DECIMALS


@dataclass
class TradeEvent:
    step:        int
    action:      str
    direction:   str
    trigger_pct: float
    price:       float
    coin_before: float
    coin_change: float
    coin_after:  float
    usd_change:  float
    vnd_change:  float
    note:        str


def pct_to_price(x0: float, pct: float) -> float:
    return x0 * (1.0 + pct / 100.0)


def simulate(
    x0: float,
    coin_init: float,
    usd_vnd: float,
    target_pct: float,
    sell_ratio: float,
    mode: str,
) -> Tuple[List[TradeEvent], float]:

    events: List[TradeEvent] = []
    coin = coin_init
    step = 0
    cash_pool: dict = {}

    triggers: List[Tuple] = []

    def collect(base: float, origin_action: str, origin_dir: str):
        if mode == "DOWN":
            if origin_action == "SEED":
                sp = base + SELL_DOWN_OFFSET
                if sp >= target_pct:
                    triggers.append((sp, "SELL", "DOWN",
                                     f"SELL DOWN @ {sp:+.2f}% (stop-loss)", None))
                    collect(sp, "SELL", "DOWN")
            elif origin_action == "SELL" and origin_dir == "DOWN":
                bp  = base + BUY_AFTER_DOWN
                sp2 = base + RESPAWN_DOWN_SELL
                if bp >= target_pct:
                    triggers.append((bp, "BUY", "DOWN",
                                     f"BUY lại @ {bp:+.2f}% (đáy tạm)", base))
                if sp2 >= target_pct:
                    triggers.append((sp2, "SELL", "DOWN",
                                     f"SELL DOWN @ {sp2:+.2f}% (stop-loss mới)", None))
                    collect(sp2, "SELL", "DOWN")
        else:
            if origin_action == "SEED":
                sp = base + SELL_UP_OFFSET
                if sp <= target_pct:
                    triggers.append((sp, "SELL", "UP",
                                     f"SELL UP @ {sp:+.2f}% (take-profit)", None))
                    collect(sp, "SELL", "UP")
            elif origin_action == "SELL" and origin_dir == "UP":
                sp2 = base + RESPAWN_UP_SELL
                if sp2 <= target_pct:
                    triggers.append((sp2, "SELL", "UP",
                                     f"SELL UP @ {sp2:+.2f}% (take-profit mới)", None))
                    collect(sp2, "SELL", "UP")

    collect(0.0, "SEED", "")

    if mode == "DOWN":
        triggers.sort(key=lambda t: t[0], reverse=True)
    else:
        triggers.sort(key=lambda t: t[0])

    for (trig_pct, action, direction, note, buy_key) in triggers:
        price = pct_to_price(x0, trig_pct)
        step += 1

        if action == "SELL":
            coin_sold = floor4(coin * sell_ratio)
            if coin_sold <= 0:
                continue
            usd_gained  = coin_sold * price
            vnd_gained  = usd_gained * usd_vnd
            coin_before = coin
            coin        = round(coin - coin_sold, COIN_DECIMALS)
            cash_pool[trig_pct] = usd_gained
            events.append(TradeEvent(
                step=step, action="SELL", direction=direction,
                trigger_pct=trig_pct, price=price,
                coin_before=coin_before, coin_change=-coin_sold,
                coin_after=coin, usd_change=usd_gained,
                vnd_change=vnd_gained, note=note,
            ))

        elif action == "BUY":
            usd_available = cash_pool.pop(buy_key, 0.0)
            if usd_available <= 0 or price <= 0:
                continue
            coin_bought = floor4(usd_available / price)
            if coin_bought <= 0:
                continue
            usd_spent   = coin_bought * price
            vnd_spent   = usd_spent * usd_vnd
            leftover    = usd_available - usd_spent
            if leftover > 0.0001:
                cash_pool[trig_pct] = leftover
            coin_before = coin
            coin        = round(coin + coin_bought, COIN_DECIMALS)
            events.append(TradeEvent(
                step=step, action="BUY", direction=direction,
                trigger_pct=trig_pct, price=price,
                coin_before=coin_before, coin_change=+coin_bought,
                coin_after=coin, usd_change=-usd_spent,
                vnd_change=-vnd_spent, note=note,
            ))

    return events, coin


def format_vnd(amount: float) -> str:
    return f"{amount:,.0f} ₫"


def format_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def print_result(
    events: List[TradeEvent],
    coin_final: float,
    x0: float,
    coin_init: float,
    target_price: float,
    usd_vnd: float,
    mode: str,
    sell_ratio: float,
):
    mode_label = "GIẢM ↓" if mode == "DOWN" else "TĂNG ↑"
    print("\n" + "═" * 72)
    print(f"  KẾT QUẢ SIMULATE — MODE {mode_label}")
    print("═" * 72)
    print(f"  Giá gốc      : {format_usd(x0)}  ({format_vnd(x0 * usd_vnd)})")
    print(f"  Coin ban đầu : {coin_init:.4f} coin")
    print(f"  Giá mục tiêu : {format_usd(target_price)}  ({format_vnd(target_price * usd_vnd)})")
    print(f"  Tỉ lệ SELL   : {sell_ratio*100:.0f}% mỗi lần  |  Làm tròn: {COIN_DECIMALS} chữ số (floor)")
    print(f"  Tỉ giá USD   : {format_vnd(usd_vnd)}/USD")

    if not events:
        print("\n  ⚠  Không có lệnh nào được trigger trong khoảng này.")
    else:
        print(f"\n{'─'*72}")
        print(f"  {'#':>3}  {'Loại':<6}  {'Hướng':<5}  {'% trigger':>10}  "
              f"{'Giá USD':>12}  {'Coin Δ':>10}  {'Coin còn':>10}")
        print(f"{'─'*72}")
        for e in events:
            sign    = "▼" if e.action == "SELL" else "▲"
            delta_s = f"{e.coin_change:+.4f}"
            print(f"  {e.step:>3}  {sign}{e.action:<5}  {e.direction:<5}  "
                  f"{e.trigger_pct:>+9.2f}%  "
                  f"{format_usd(e.price):>12}  "
                  f"{delta_s:>10}  "
                  f"{e.coin_after:>10.4f}")
            print(f"       └ {e.note}")
            if e.action == "SELL":
                print(f"         Thu được : {format_usd(e.usd_change)}  ({format_vnd(e.vnd_change)})")
            else:
                print(f"         Chi ra   : {format_usd(-e.usd_change)}  ({format_vnd(-e.vnd_change)})")

    # ── BUY toàn bộ tiền SELL dư tại giá mục tiêu ────────────────────
    total_sell_usd = sum(e.usd_change  for e in events if e.action == "SELL")
    total_buy_usd  = sum(-e.usd_change for e in events if e.action == "BUY")
    cash_remaining = total_sell_usd - total_buy_usd

    coin_from_cash = floor4(cash_remaining / target_price) if target_price > 0 else 0.0
    coin_total     = round(coin_final + coin_from_cash, COIN_DECIMALS)

    usd_total = coin_total * target_price
    vnd_total = usd_total * usd_vnd
    usd_init  = coin_init * x0
    vnd_init  = usd_init * usd_vnd
    pnl_usd   = usd_total - usd_init
    pnl_vnd   = vnd_total - vnd_init
    pnl_pct   = (pnl_vnd / vnd_init * 100) if vnd_init > 0 else 0
    pnl_sign  = "+" if pnl_vnd >= 0 else ""

    print(f"\n{'═'*72}")
    print(f"  KẾT QUẢ CUỐI")
    print(f"{'─'*72}")
    print(f"  Coin giữ (chưa BUY dư)  : {coin_final:.4f} coin")
    if cash_remaining > 0.0001:
        usd_spent_from_cash = coin_from_cash * target_price
        print(f"  Tiền SELL dư            : {format_usd(cash_remaining)}  ({format_vnd(cash_remaining * usd_vnd)})")
        print(f"  → BUY @ {format_usd(target_price):>10}          : +{coin_from_cash:.4f} coin  "
              f"(chi {format_usd(usd_spent_from_cash)})")
    print(f"{'─'*72}")
    print(f"  Tổng coin               : {coin_total:.4f} coin")
    print(f"  Giá trị tại mục tiêu    : {format_usd(usd_total)}  ({format_vnd(vnd_total)})")
    print(f"  Vốn ban đầu             : {format_usd(usd_init)}  ({format_vnd(vnd_init)})")
    print(f"  P&L                     : {pnl_sign}{format_usd(pnl_usd)}  "
          f"({pnl_sign}{format_vnd(pnl_vnd)})  [{pnl_sign}{pnl_pct:.2f}%]")
    print(f"{'═'*72}\n")


def get_float(prompt: str, min_val: float = None, max_val: float = None) -> float:
    while True:
        try:
            val = float(input(prompt).strip().replace(",", ""))
            if min_val is not None and val < min_val:
                print(f"  ⚠  Giá trị phải ≥ {min_val}")
                continue
            if max_val is not None and val > max_val:
                print(f"  ⚠  Giá trị phải ≤ {max_val}")
                continue
            return val
        except ValueError:
            print("  ⚠  Giá trị không hợp lệ, nhập lại.")


def main():
    print("═" * 72)
    print("  COIN SIMULATOR — TaskEngine Spawn Logic")
    print(f"  Làm tròn coin: {COIN_DECIMALS} chữ số thập phân (floor)")
    print("═" * 72)

    print("\n[ THÔNG TIN CƠ BẢN ]")
    x0        = get_float("  Giá coin gốc (USD)         : ", min_val=0.000001)
    coin_init = get_float("  Số coin đang có             : ", min_val=0.0001)
    usd_vnd   = get_float("  Tỉ giá USD/VND              : ", min_val=1)
    sell_pct  = get_float("  Tỉ lệ SELL mỗi lần (%)     : ", min_val=0.01, max_val=100)
    sell_ratio = sell_pct / 100.0

    coin_init = floor4(coin_init)
    print(f"  → Coin ban đầu (làm tròn)  : {coin_init:.4f} coin")

    print("\n[ CHỌN MODE ]")
    print("  1. Giá TĂNG lên")
    print("  2. Giá GIẢM xuống")
    print("  3. Cả hai")
    while True:
        mode_input = input("  Chọn (1/2/3): ").strip()
        if mode_input in ("1", "2", "3"):
            break
        print("  ⚠  Nhập 1, 2 hoặc 3.")

    run_up   = mode_input in ("1", "3")
    run_down = mode_input in ("2", "3")
    price_up = price_down = None

    if run_up:
        print("\n[ MODE TĂNG ]")
        price_up = get_float(f"  Giá coin tăng tới (USD) [> {x0}] : ", min_val=x0 * 1.000001)

    if run_down:
        print("\n[ MODE GIẢM ]")
        price_down = get_float(f"  Giá coin giảm còn (USD) [< {x0}] : ",
                               min_val=0.000001, max_val=x0 * 0.999999)

    if run_up:
        target_pct = (price_up / x0 - 1.0) * 100.0
        events, coin_final = simulate(x0, coin_init, usd_vnd, target_pct, sell_ratio, "UP")
        print_result(events, coin_final, x0, coin_init, price_up, usd_vnd, "UP", sell_ratio)

    if run_down:
        target_pct = (price_down / x0 - 1.0) * 100.0
        events, coin_final = simulate(x0, coin_init, usd_vnd, target_pct, sell_ratio, "DOWN")
        print_result(events, coin_final, x0, coin_init, price_down, usd_vnd, "DOWN", sell_ratio)


if __name__ == "__main__":
    main()