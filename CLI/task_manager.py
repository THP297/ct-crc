#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task_manager.py — Quản lý multi-section TaskEngine
Mỗi section có x0 riêng, id task độc lập, coin riêng.
Aggregate board BUY / SELL từ tất cả section.
Validation: x0 mới phải nằm trên cấp số cộng 3% của x0_base (section 1).
"""

import math
import itertools
import heapq
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# ── Spawn constants (giống coin_simulator) ─────────────────────────
SELL_DOWN_OFFSET  = -2.0
SELL_UP_OFFSET    = +3.0
BUY_AFTER_DOWN    = -3.0
BUY_AFTER_UP      = -2.5
RESPAWN_DOWN_SELL = -2.0
RESPAWN_UP_SELL   = +3.0
COIN_DECIMALS     = 4
WARN_STEP_PCT     = 3.0   # cấp số cộng 3%


def floor4(x: float) -> float:
    return math.floor(x * 10**COIN_DECIMALS) / 10**COIN_DECIMALS


def pct_to_price(x0: float, pct: float) -> float:
    return x0 * (1.0 + pct / 100.0)


# ── Task dataclass ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Task:
    id: int
    section_id: int
    direction: str    # "UP" | "DOWN"
    action: str       # "BUY" | "SELL"
    target_pct: float # % so với x0 của section đó
    target_price: float
    note: str


# ── Section ─────────────────────────────────────────────────────────
@dataclass
class Section:
    id: int
    x0: float
    coin_init: float
    sell_ratio: float
    label: str = ""

    # heaps — same lazy-deletion pattern như TaskEngine gốc
    up_heap:   List = field(default_factory=list)
    down_heap: List = field(default_factory=list)
    cancelled: set  = field(default_factory=set)
    sibling_map: Dict[int, Task] = field(default_factory=dict)

    triggered: List[Task] = field(default_factory=list)
    closed:    List[Task]  = field(default_factory=list)

    # portfolio state
    coin: float = 0.0
    cash_pool: Dict[float, float] = field(default_factory=dict)

    def __post_init__(self):
        self.coin = floor4(self.coin_init)


# ── TaskManager ─────────────────────────────────────────────────────
class TaskManager:
    """
    Quản lý nhiều Section.
    - Section đầu tiên xác định x0_base (cấp số cộng 3%).
    - Section mới phải có x0 là x0_base * (1.03)^n hoặc x0_base * (0.97)^n
      với n nguyên dương, tolerance ±0.5%.
    """

    STEP_RATIO = 1.0 + WARN_STEP_PCT / 100.0   # 1.03

    def __init__(self):
        self._id_gen   = itertools.count(1)
        self._sec_gen  = itertools.count(1)
        self.sections: Dict[int, Section] = {}
        self.x0_base: Optional[float] = None

    # ── Validation ───────────────────────────────────────────────────

    def _geometric_suggestions(self, x0_base: float, n: int = 5) -> List[float]:
        """Trả về n mức UP và n mức DOWN theo cấp số cộng 3%."""
        up   = [x0_base * (self.STEP_RATIO ** i) for i in range(1, n + 1)]
        down = [x0_base / (self.STEP_RATIO ** i) for i in range(1, n + 1)]
        return sorted(up + down)

    def validate_x0(self, x0_new: float, tol: float = 0.005) -> Tuple[bool, Optional[float], str]:
        """
        Kiểm tra x0_new có nằm trên cấp số cộng 3% của x0_base không.
        Trả về (ok, nearest_suggestion, message).
        """
        if self.x0_base is None:
            return True, None, ""

        base = self.x0_base
        ratio = self.STEP_RATIO

        # Tìm n gần nhất: n = log(x0_new/base) / log(ratio)
        n_float = math.log(x0_new / base) / math.log(ratio)
        n_round = round(n_float)

        if n_round == 0:
            # Trùng x0_base
            suggestions = self._geometric_suggestions(base, 5)
            nearest = min(suggestions, key=lambda s: abs(s - x0_new))
            return False, nearest, (
                f"x0 mới trùng với x0_base ({base:,.2f}). "
                f"Gợi ý gần nhất: ${nearest:,.2f}"
            )

        expected = base * (ratio ** n_round)
        err = abs(x0_new - expected) / expected

        if err <= tol:
            return True, expected, f"Hợp lệ — nằm tại bậc {n_round:+d} ({expected:,.2f})"

        # Không hợp lệ → tìm gợi ý gần nhất
        suggestions = self._geometric_suggestions(base, 10)
        nearest = min(suggestions, key=lambda s: abs(s - x0_new))
        msg = (
            f"x0 ${x0_new:,.2f} không nằm trên cấp số cộng 3% của x0_base ${base:,.2f}.\n"
            f"  Gần nhất UP  : " +
            "  |  ".join(f"${s:,.2f}" for s in sorted(suggestions) if s > base)[:80] +
            f"\n  Gần nhất DOWN: " +
            "  |  ".join(f"${s:,.2f}" for s in sorted(suggestions, reverse=True) if s < base)[:80] +
            f"\n  → Gợi ý gần nhất: ${nearest:,.2f}"
        )
        return False, nearest, msg

    # ── Add Section ──────────────────────────────────────────────────

    def add_section(self, x0: float, coin_init: float, sell_ratio: float,
                    label: str = "", force: bool = False) -> Optional[Section]:
        ok, nearest, msg = self.validate_x0(x0)
        if not ok:
            print(f"\n⚠  CẢNH BÁO: {msg}")
            if not force:
                print("  Dùng force=True hoặc nhập lại với giá gợi ý.")
                return None

        sec_id = next(self._sec_gen)
        sec = Section(
            id=sec_id,
            x0=x0,
            coin_init=coin_init,
            sell_ratio=sell_ratio,
            label=label or f"Section {sec_id}",
        )
        self.sections[sec_id] = sec

        if self.x0_base is None:
            self.x0_base = x0
            print(f"[INIT] x0_base = ${x0:,.2f}  (cấp số cộng ±3%)")

        # Seed tasks
        self._seed(sec)
        print(f"[SECTION {sec_id}] '{sec.label}'  x0=${x0:,.2f}  "
              f"coin={coin_init:.4f}  sell={sell_ratio*100:.0f}%")
        return sec

    # ── Task helpers ─────────────────────────────────────────────────

    def _new_task(self, sec: Section, direction: str, target_pct: float,
                  action: str, note: str) -> Optional[Task]:
        if target_pct < -98 or target_pct > 98:
            return None
        t = Task(
            id           = next(self._id_gen),
            section_id   = sec.id,
            direction    = direction,
            action       = action,
            target_pct   = target_pct,
            target_price = pct_to_price(sec.x0, target_pct),
            note         = note,
        )
        if direction == "UP":
            heapq.heappush(sec.up_heap, (t.target_pct, t.id, t))
        else:
            heapq.heappush(sec.down_heap, (-t.target_pct, t.id, t))
        return t

    def _link(self, sec: Section, a: Optional[Task], b: Optional[Task]):
        if a and b:
            sec.sibling_map[a.id] = b
            sec.sibling_map[b.id] = a

    def _cancel(self, sec: Section, task: Task, reason: str):
        if task.id in sec.cancelled:
            return
        sec.cancelled.add(task.id)
        sec.sibling_map.pop(task.id, None)
        sec.closed.append(task)

    def _cancel_sibling(self, sec: Section, task: Task):
        sib = sec.sibling_map.pop(task.id, None)
        if sib is None:
            return
        sec.sibling_map.pop(sib.id, None)
        if sib.action == "SELL":
            self._cancel(sec, sib, f"sibling #{task.id} triggered")

    def _cancel_all_sell_up(self, sec: Section):
        for _, tid, t in sec.up_heap:
            if tid in sec.cancelled:
                continue
            if t.action == "SELL":
                sib = sec.sibling_map.pop(tid, None)
                if sib:
                    sec.sibling_map.pop(sib.id, None)
                self._cancel(sec, t, "SELL DOWN triggered — reset SELL UP")

    # ── Seed & Spawn ─────────────────────────────────────────────────

    def _seed(self, sec: Section):
        t1 = self._new_task(sec, "DOWN", SELL_DOWN_OFFSET, "SELL",
                            f"SELL nếu giảm 2% → ${pct_to_price(sec.x0, SELL_DOWN_OFFSET):,.2f}")
        t2 = self._new_task(sec, "UP",   SELL_UP_OFFSET,  "SELL",
                            f"SELL nếu tăng 3% → ${pct_to_price(sec.x0, SELL_UP_OFFSET):,.2f}")
        self._link(sec, t1, t2)

    def _spawn_sell_down(self, sec: Section, base_pct: float):
        self._cancel_all_sell_up(sec)
        t_buy = self._new_task(sec, "DOWN", base_pct + BUY_AFTER_DOWN, "BUY",
                               f"BUY lại @ {base_pct+BUY_AFTER_DOWN:+.2f}% → ${pct_to_price(sec.x0, base_pct+BUY_AFTER_DOWN):,.2f}")
        t_sd  = self._new_task(sec, "DOWN", base_pct + RESPAWN_DOWN_SELL, "SELL",
                               f"SELL stop-loss @ {base_pct+RESPAWN_DOWN_SELL:+.2f}% → ${pct_to_price(sec.x0, base_pct+RESPAWN_DOWN_SELL):,.2f}")
        t_su  = self._new_task(sec, "UP",   base_pct + RESPAWN_UP_SELL,  "SELL",
                               f"SELL take-profit @ {base_pct+RESPAWN_UP_SELL:+.2f}% → ${pct_to_price(sec.x0, base_pct+RESPAWN_UP_SELL):,.2f}")
        self._link(sec, t_sd, t_su)

    def _spawn_sell_up(self, sec: Section, base_pct: float):
        self._new_task(sec, "DOWN", base_pct + BUY_AFTER_UP, "BUY",
                       f"BUY lại @ {base_pct+BUY_AFTER_UP:+.2f}% → ${pct_to_price(sec.x0, base_pct+BUY_AFTER_UP):,.2f}")
        t_sd = self._new_task(sec, "DOWN", base_pct + RESPAWN_DOWN_SELL, "SELL",
                              f"SELL stop-loss @ {base_pct+RESPAWN_DOWN_SELL:+.2f}% → ${pct_to_price(sec.x0, base_pct+RESPAWN_DOWN_SELL):,.2f}")
        t_su = self._new_task(sec, "UP",   base_pct + RESPAWN_UP_SELL,  "SELL",
                              f"SELL take-profit @ {base_pct+RESPAWN_UP_SELL:+.2f}% → ${pct_to_price(sec.x0, base_pct+RESPAWN_UP_SELL):,.2f}")
        self._link(sec, t_sd, t_su)

    # ── Trigger ──────────────────────────────────────────────────────

    def _trigger(self, sec: Section, task: Task, current_price: float):
        current_pct = (current_price / sec.x0 - 1) * 100
        sec.triggered.append(task)
        self._cancel_sibling(sec, task)

        # Portfolio update
        if task.action == "SELL":
            coin_sold = floor4(sec.coin * sec.sell_ratio)
            usd       = coin_sold * current_price
            sec.coin  = round(sec.coin - coin_sold, COIN_DECIMALS)
            sec.cash_pool[task.target_pct] = usd
        elif task.action == "BUY":
            usd = sec.cash_pool.pop(
                # BUY_AFTER_DOWN hoặc BUY_AFTER_UP → key = base SELL tương ứng
                round(task.target_pct - BUY_AFTER_DOWN, 4),
                sec.cash_pool.pop(round(task.target_pct - BUY_AFTER_UP, 4), 0.0)
            )
            if usd > 0:
                bought   = floor4(usd / current_price)
                sec.coin = round(sec.coin + bought, COIN_DECIMALS)

        # Spawn
        if task.action == "SELL":
            if task.direction == "DOWN":
                self._spawn_sell_down(sec, current_pct)
            else:
                self._spawn_sell_up(sec, current_pct)

    def process_price(self, price: float) -> List[Tuple[Section, Task]]:
        """Kiểm tra giá mới với tất cả section, trả về list task vừa trigger."""
        fired = []
        for sec in self.sections.values():
            pct = (price / sec.x0 - 1) * 100

            # UP
            while sec.up_heap:
                _, tid, _ = sec.up_heap[0]
                if tid in sec.cancelled:
                    heapq.heappop(sec.up_heap); sec.cancelled.discard(tid); continue
                if pct >= sec.up_heap[0][0]:
                    _, _, task = heapq.heappop(sec.up_heap)
                    if task.id in sec.cancelled:
                        sec.cancelled.discard(task.id); continue
                    self._trigger(sec, task, price)
                    fired.append((sec, task))
                else:
                    break

            # DOWN
            while sec.down_heap:
                _, tid, _ = sec.down_heap[0]
                if tid in sec.cancelled:
                    heapq.heappop(sec.down_heap); sec.cancelled.discard(tid); continue
                top = -sec.down_heap[0][0]
                if pct <= top:
                    _, _, task = heapq.heappop(sec.down_heap)
                    if task.id in sec.cancelled:
                        sec.cancelled.discard(task.id); continue
                    self._trigger(sec, task, price)
                    fired.append((sec, task))
                else:
                    break

        return fired

    # ── Pending tasks (for display & alert) ──────────────────────────

    def all_pending_tasks(self) -> List[Task]:
        tasks = []
        for sec in self.sections.values():
            for _, tid, t in sec.up_heap:
                if tid not in sec.cancelled:
                    tasks.append(t)
            for _, tid, t in sec.down_heap:
                if tid not in sec.cancelled:
                    tasks.append(t)
        return tasks

    def pending_buy_tasks(self) -> List[Task]:
        return [t for t in self.all_pending_tasks() if t.action == "BUY"]

    def pending_sell_tasks(self) -> List[Task]:
        return [t for t in self.all_pending_tasks() if t.action == "SELL"]

    # ── Display ──────────────────────────────────────────────────────

    def print_boards(self, current_price: Optional[float] = None):
        sep = "═" * 74

        def _rows(tasks: List[Task], label: str):
            print(f"\n{sep}")
            print(f"  BOARD: {label}  ({len(tasks)} tasks pending)")
            print(sep)
            if not tasks:
                print("  (trống)")
                return
            print(f"  {'ID':>5}  {'Sec':>4}  {'Dir':<5}  {'Target%':>9}  "
                  f"{'Target$':>12}  {'Note'}")
            print("─" * 74)
            for t in sorted(tasks, key=lambda x: x.target_price):
                dist = ""
                if current_price:
                    d = (t.target_price - current_price) / current_price * 100
                    dist = f"  [{d:+.2f}% từ giá HT]"
                print(f"  #{t.id:>4}  S{t.section_id:<3}  {t.direction:<5}  "
                      f"{t.target_pct:>+8.2f}%  "
                      f"${t.target_price:>11,.2f}  {t.note}{dist}")

        buy_tasks  = self.pending_buy_tasks()
        sell_tasks = self.pending_sell_tasks()
        _rows(sell_tasks, "SELL")
        _rows(buy_tasks,  "BUY")

        # Section summary
        print(f"\n{sep}")
        print(f"  SECTION SUMMARY")
        print(sep)
        print(f"  {'ID':>4}  {'Label':<20}  {'x0':>12}  {'Coin':>10}  {'Sell%':>6}")
        print("─" * 74)
        for sec in self.sections.values():
            print(f"  S{sec.id:<3}  {sec.label:<20}  ${sec.x0:>11,.2f}  "
                  f"{sec.coin:>10.4f}  {sec.sell_ratio*100:>5.0f}%")
        print(sep)
