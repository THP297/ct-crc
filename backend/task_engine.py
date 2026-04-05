import logging
from typing import Any

logger = logging.getLogger(__name__)


def _value_to_pct(x0: float, x: float) -> float:
    return (x / x0 - 1.0) * 100.0


def _spawn_pair(
    symbol: str,
    t1_dir: str, t1_target: float, t1_action: str, t1_note: str,
    t2_dir: str, t2_target: float, t2_action: str, t2_note: str,
    add_fn, update_sibling_fn,
    t1_sell_origin: str = "", t2_sell_origin: str = "",
) -> list[dict]:
    """Create two tasks and link them as siblings."""
    t1 = add_fn(symbol, t1_dir, t1_target, t1_action, t1_note, sell_origin=t1_sell_origin)
    t2 = add_fn(symbol, t2_dir, t2_target, t2_action, t2_note, sell_origin=t2_sell_origin)

    if t1 and t2:
        update_sibling_fn(t1["id"], t2["id"])
        update_sibling_fn(t2["id"], t1["id"])
        t1["sibling_id"] = t2["id"]
        t2["sibling_id"] = t1["id"]

    return [t for t in (t1, t2) if t]


def _cancel_task(symbol: str, task: dict, current_pct: float, current_x: float,
                 reason: str, sibling_triggered_id: int | None = None) -> None:
    """Shared helper: remove task from queue and record it as closed."""
    from .store import remove_task_from_queue, add_closed_task
    remove_task_from_queue(task["id"])
    add_closed_task(
        symbol=symbol,
        closed_task_id=task["id"],
        sibling_triggered_id=sibling_triggered_id,
        direction=task["direction"],
        action=task["action"],
        target_pct=task["target_pct"],
        at_pct=current_pct,
        at_price=current_x,
        reason=reason,
        note=task.get("note", ""),
    )


def _cancel_all_pending_sell_up(symbol: str, current_pct: float,
                                current_x: float) -> set[int]:
    """Cancel every pending SELL UP task. Called when SELL DOWN triggers."""
    from .store import load_task_queue, update_task_sibling_id
    tasks = load_task_queue(symbol)
    cancelled: set[int] = set()
    for t in tasks:
        if t["direction"] == "UP" and t["action"] == "SELL":
            sib_id = t.get("sibling_id")
            if sib_id:
                update_task_sibling_id(sib_id, 0)
            _cancel_task(symbol, t, current_pct, current_x,
                         "SELL DOWN triggered — reset SELL UP cũ")
            cancelled.add(t["id"])
    return cancelled


def _cancel_sibling(symbol: str, triggered_task: dict, current_pct: float,
                    current_x: float, tasks: list[dict]) -> None:
    """Cancel the sibling of a triggered task (only if sibling is SELL)."""
    sibling_id = triggered_task.get("sibling_id")
    if not sibling_id:
        return

    sibling = next((t for t in tasks if t["id"] == sibling_id), None)
    if sibling is None:
        return

    if sibling["action"] == "BUY":
        return

    _cancel_task(
        symbol, sibling, current_pct, current_x,
        f"Sibling #{triggered_task['id']} [{triggered_task['direction']}] triggered",
        sibling_triggered_id=triggered_task["id"],
    )


def process_new_price(symbol: str, new_x: float) -> dict[str, Any]:
    """
    Nhập giá mới cho symbol đã được init_engine.
    Tính current_pct, trigger tasks bị vượt mốc, cancel sibling, spawn task mới.
    """
    from .store import (
        load_task_engine_state,
        save_task_engine_state,
        load_task_queue,
        add_task_to_queue,
        update_task_sibling_id,
        remove_task_from_queue,
        add_passed_task,
        load_passed_tasks,
        load_closed_tasks,
    )

    if new_x <= 0:
        return {"error": "Price must be > 0"}

    state = load_task_engine_state(symbol)

    if state is None:
        return {"error": f"Engine not initialized for {symbol}. Call init first."}

    x0 = state["x0"]
    prev_pct = state["current_pct"]

    current_pct = _value_to_pct(x0, new_x)
    delta_pct = current_pct - prev_pct

    state["current_x"] = new_x
    state["current_pct"] = current_pct
    save_task_engine_state(symbol, state)

    triggered = []
    spawned = []

    while True:
        triggered_any = False
        tasks = load_task_queue(symbol)

        for task in tasks:
            hit = False
            if task["direction"] == "UP" and current_pct >= task["target_pct"]:
                hit = True
            elif task["direction"] == "DOWN" and current_pct <= task["target_pct"]:
                hit = True

            if hit:
                remove_task_from_queue(task["id"])
                add_passed_task(
                    symbol=symbol,
                    task_id=task["id"],
                    direction=task["direction"],
                    action=task["action"],
                    target_pct=task["target_pct"],
                    hit_pct=current_pct,
                    hit_price=new_x,
                    note=task.get("note", ""),
                    sell_origin=task.get("sell_origin", ""),
                )

                _cancel_sibling(symbol, task, current_pct, new_x, tasks)

                new_tasks = _spawn_after_trigger(
                    symbol, task["direction"], task["action"],
                    current_pct, new_x,
                    add_task_to_queue, update_task_sibling_id,
                )
                triggered.append(task)
                spawned.extend(new_tasks)
                triggered_any = True
                break  # re-load queue — _cancel_all_pending_sell_up may have mutated it

        if not triggered_any:
            break

    final_state = load_task_engine_state(symbol)
    final_tasks = load_task_queue(symbol)
    passed = load_passed_tasks(symbol)
    closed = load_closed_tasks(symbol)

    up_tasks = sorted(
        [t for t in final_tasks if t["direction"] == "UP"],
        key=lambda t: t["target_pct"],
    )
    down_tasks = sorted(
        [t for t in final_tasks if t["direction"] == "DOWN"],
        key=lambda t: t["target_pct"],
        reverse=True,
    )

    return {
        "state": final_state,
        "delta_pct": delta_pct,
        "triggered": triggered,
        "spawned": spawned,
        "up_tasks": up_tasks,
        "down_tasks": down_tasks,
        "passed_tasks": passed,
        "closed_tasks": closed,
    }


def _spawn_after_trigger(
    symbol: str,
    direction: str,
    action: str,
    current_pct: float,
    current_x: float,
    add_fn,
    update_sibling_fn,
) -> list[dict]:
    """
    Spawn tasks after trigger.
    BUY trigger  → no spawn
    SELL + DOWN  → cancel all pending SELL UP, then spawn:
                     DOWN BUY  @ base-3%  (no sibling)
                     DOWN SELL @ base-2%  ↔  UP SELL @ base+3%
    SELL + UP    → spawn:
                     DOWN BUY  @ base-2.5% (no sibling)
                     DOWN SELL @ base-2%   ↔  UP SELL @ base+3%
    """
    base = current_pct

    if action == "BUY":
        return []

    if direction == "DOWN":
        _cancel_all_pending_sell_up(symbol, current_pct, current_x)

        t_buy = add_fn(symbol, "DOWN", base - 3.0, "BUY",
                       f"BUY lại nếu x giảm thêm 3% (tới {base - 3.0:+.4f}%)",
                       sell_origin="SELL_DOWN")
        t_sell_down = add_fn(symbol, "DOWN", base - 2.0, "SELL",
                             f"SELL (stop-loss) nếu x giảm thêm 2% (tới {base - 2.0:+.4f}%)")
        t_sell_up = add_fn(symbol, "UP", base + 3.0, "SELL",
                           f"SELL (take-profit) nếu x tăng 3% (tới {base + 3.0:+.4f}%)")
        if t_sell_down and t_sell_up:
            update_sibling_fn(t_sell_down["id"], t_sell_up["id"])
            update_sibling_fn(t_sell_up["id"], t_sell_down["id"])
            t_sell_down["sibling_id"] = t_sell_up["id"]
            t_sell_up["sibling_id"] = t_sell_down["id"]
        return [t for t in (t_buy, t_sell_down, t_sell_up) if t]

    # direction == "UP" → 3 tasks
    t_buy = add_fn(symbol, "DOWN", base - 2.5, "BUY",
                   f"BUY lại nếu x giảm thêm 2.5% (tới {base - 2.5:+.4f}%)",
                   sell_origin="SELL_UP")
    t_sell_down = add_fn(symbol, "DOWN", base - 2.0, "SELL",
                         f"SELL (stop-loss) nếu x giảm thêm 2% (tới {base - 2.0:+.4f}%)")
    t_sell_up = add_fn(symbol, "UP", base + 3.0, "SELL",
                       f"SELL (take-profit) nếu x tăng 3% (tới {base + 3.0:+.4f}%)")
    if t_sell_down and t_sell_up:
        update_sibling_fn(t_sell_down["id"], t_sell_up["id"])
        update_sibling_fn(t_sell_up["id"], t_sell_down["id"])
        t_sell_down["sibling_id"] = t_sell_up["id"]
        t_sell_up["sibling_id"] = t_sell_down["id"]
    return [t for t in (t_buy, t_sell_down, t_sell_up) if t]


def init_engine(symbol: str, x0: float, coin_qty: float = 0.0) -> dict[str, Any]:
    """
    Khởi tạo engine cho symbol với giá gốc x0.
    Spawn ngay 2 task mặc định (sibling pair): DOWN/SELL -2% | UP/SELL +3%.
    """
    from .store import (
        save_task_engine_state,
        clear_task_queue_for_symbol,
        clear_passed_tasks_for_symbol,
        clear_closed_tasks_for_symbol,
        add_task_to_queue,
        update_task_sibling_id,
        load_task_queue,
        ensure_settings,
    )

    if x0 <= 0:
        return {"error": "Base price must be > 0"}

    clear_task_queue_for_symbol(symbol)
    clear_passed_tasks_for_symbol(symbol)
    clear_closed_tasks_for_symbol(symbol)
    ensure_settings(symbol)

    state = {
        "symbol": symbol,
        "x0": x0,
        "current_x": x0,
        "current_pct": 0.0,
        "seeded": True,
        "coin_qty": coin_qty,
    }
    save_task_engine_state(symbol, state)

    base = 0.0
    down_t = base - 2.0
    up_t = base + 3.0
    _spawn_pair(
        symbol,
        "DOWN", down_t, "SELL",
        f"SELL nếu x giảm 2% (tới {down_t:+.4f}%)",
        "UP", up_t, "SELL",
        f"SELL nếu x tăng 3% (tới {up_t:+.4f}%)",
        add_task_to_queue, update_task_sibling_id,
    )

    tasks = load_task_queue(symbol)
    up_tasks = sorted(
        [t for t in tasks if t["direction"] == "UP"],
        key=lambda t: t["target_pct"],
    )
    down_tasks = sorted(
        [t for t in tasks if t["direction"] == "DOWN"],
        key=lambda t: t["target_pct"],
        reverse=True,
    )

    return {
        "state": state,
        "up_tasks": up_tasks,
        "down_tasks": down_tasks,
    }


def get_engine_info(symbol: str) -> dict[str, Any]:
    from .store import load_engine_info_batched

    info = load_engine_info_batched(symbol)
    state = info["state"]
    if state is None:
        return {
            "state": None, "up_tasks": [], "down_tasks": [],
            "passed_tasks": [], "closed_tasks": [],
        }

    tasks = info["tasks"]
    up_tasks = sorted(
        [t for t in tasks if t["direction"] == "UP"],
        key=lambda t: t["target_pct"],
    )
    down_tasks = sorted(
        [t for t in tasks if t["direction"] == "DOWN"],
        key=lambda t: t["target_pct"],
        reverse=True,
    )

    return {
        "state": state,
        "up_tasks": up_tasks,
        "down_tasks": down_tasks,
        "passed_tasks": info["passed"],
        "closed_tasks": info["closed"],
    }


def get_all_engine_symbols() -> list[str]:
    from .store import load_all_task_engine_symbols
    return load_all_task_engine_symbols()


# ──────────────────────────────────────────────────────────────
# SECTION-BASED API
# ──────────────────────────────────────────────────────────────

def create_section(symbol: str, name: str, x0: float, coin_qty: float = 0.0) -> dict[str, Any]:
    from .store import (
        create_section as _create_section,
        add_task_to_queue_for_section,
        update_task_sibling_id,
        load_task_queue_by_section,
        ensure_settings,
    )

    if x0 <= 0:
        return {"error": "Base price must be > 0"}
    if not name.strip():
        return {"error": "Section name is required"}

    ensure_settings(symbol)

    sec = _create_section(symbol, name.strip(), x0, coin_qty)
    if sec is None:
        return {"error": "Failed to create section"}

    section_id = sec["id"]

    def add_fn(sym, direction, target_pct, action, note, sell_origin=""):
        return add_task_to_queue_for_section(
            section_id, sym, direction, target_pct, action, note, sell_origin=sell_origin)

    base = 0.0
    down_t = base - 2.0
    up_t = base + 3.0
    _spawn_pair(
        symbol, "DOWN", down_t, "SELL",
        f"SELL nếu x giảm 2% (tới {down_t:+.4f}%)",
        "UP", up_t, "SELL",
        f"SELL nếu x tăng 3% (tới {up_t:+.4f}%)",
        add_fn, update_task_sibling_id,
    )

    tasks = load_task_queue_by_section(section_id)
    up_tasks = sorted([t for t in tasks if t["direction"] == "UP"], key=lambda t: t["target_pct"])
    down_tasks = sorted([t for t in tasks if t["direction"] == "DOWN"], key=lambda t: t["target_pct"], reverse=True)

    return {"section": sec, "up_tasks": up_tasks, "down_tasks": down_tasks}


def delete_section_cmd(section_id: int) -> dict[str, Any]:
    from .store import load_section, delete_section as _delete
    sec = load_section(section_id)
    if sec is None:
        return {"error": f"Section {section_id} not found"}
    _delete(section_id)
    return {"ok": True, "deleted_section": sec}


def get_section_info(section_id: int) -> dict[str, Any]:
    from .store import load_section_info_batched

    info = load_section_info_batched(section_id)
    sec = info["section"]
    if sec is None:
        return {"section": None, "up_tasks": [], "down_tasks": [], "passed_tasks": [], "closed_tasks": []}

    tasks = info["tasks"]
    up_tasks = sorted([t for t in tasks if t["direction"] == "UP"], key=lambda t: t["target_pct"])
    down_tasks = sorted([t for t in tasks if t["direction"] == "DOWN"], key=lambda t: t["target_pct"], reverse=True)

    return {
        "section": sec,
        "up_tasks": up_tasks,
        "down_tasks": down_tasks,
        "passed_tasks": info["passed"],
        "closed_tasks": info["closed"],
    }


def list_sections(symbol: str | None = None) -> list[dict[str, Any]]:
    from .store import load_sections
    return load_sections(symbol)


def _process_section_price(section_id: int, symbol: str, x0: float,
                            prev_pct: float, new_x: float) -> dict[str, Any]:
    """Process price update for a single section. Core trigger/spawn logic."""
    from .store import (
        save_section_state,
        load_task_queue_by_section,
        add_task_to_queue_for_section,
        update_task_sibling_id,
        remove_task_from_queue,
        add_passed_task_for_section,
        add_closed_task_for_section,
    )

    current_pct = _value_to_pct(x0, new_x)
    delta_pct = current_pct - prev_pct

    save_section_state(section_id, new_x, current_pct)

    triggered = []
    spawned = []

    def cancel_task_sec(task, reason, sibling_triggered_id=None):
        remove_task_from_queue(task["id"])
        add_closed_task_for_section(
            section_id, symbol,
            closed_task_id=task["id"],
            sibling_triggered_id=sibling_triggered_id,
            direction=task["direction"],
            action=task["action"],
            target_pct=task["target_pct"],
            at_pct=current_pct,
            at_price=new_x,
            reason=reason,
            note=task.get("note", ""),
        )

    def cancel_sibling_sec(triggered_task, tasks):
        sibling_id = triggered_task.get("sibling_id")
        if not sibling_id:
            return
        sibling = next((t for t in tasks if t["id"] == sibling_id), None)
        if sibling is None or sibling["action"] == "BUY":
            return
        cancel_task_sec(sibling,
                        f"Sibling #{triggered_task['id']} [{triggered_task['direction']}] triggered",
                        sibling_triggered_id=triggered_task["id"])

    def cancel_all_sell_up_sec():
        tasks = load_task_queue_by_section(section_id)
        for t in tasks:
            if t["direction"] == "UP" and t["action"] == "SELL":
                sib_id = t.get("sibling_id")
                if sib_id:
                    update_task_sibling_id(sib_id, 0)
                cancel_task_sec(t, "SELL DOWN triggered — reset SELL UP cũ")

    def add_fn(sym, direction, target_pct, action, note, sell_origin=""):
        return add_task_to_queue_for_section(
            section_id, sym, direction, target_pct, action, note, sell_origin=sell_origin)

    while True:
        triggered_any = False
        tasks = load_task_queue_by_section(section_id)
        for task in tasks:
            hit = False
            if task["direction"] == "UP" and current_pct >= task["target_pct"]:
                hit = True
            elif task["direction"] == "DOWN" and current_pct <= task["target_pct"]:
                hit = True
            if hit:
                remove_task_from_queue(task["id"])
                add_passed_task_for_section(
                    section_id, symbol,
                    direction=task["direction"],
                    action=task["action"],
                    target_pct=task["target_pct"],
                    hit_pct=current_pct,
                    hit_price=new_x,
                    note=task.get("note", ""),
                    task_id=task["id"],
                    sell_origin=task.get("sell_origin", ""),
                )
                cancel_sibling_sec(task, tasks)

                # Spawn after trigger
                action = task["action"]
                direction = task["direction"]
                base = current_pct
                new_tasks = []
                if action == "BUY":
                    pass
                elif direction == "DOWN":
                    cancel_all_sell_up_sec()
                    t_buy = add_fn(symbol, "DOWN", base - 3.0, "BUY",
                                   f"BUY lại nếu x giảm thêm 3% (tới {base - 3.0:+.4f}%)",
                                   sell_origin="SELL_DOWN")
                    t_sd = add_fn(symbol, "DOWN", base - 2.0, "SELL",
                                  f"SELL (stop-loss) nếu x giảm thêm 2% (tới {base - 2.0:+.4f}%)")
                    t_su = add_fn(symbol, "UP", base + 3.0, "SELL",
                                  f"SELL (take-profit) nếu x tăng 3% (tới {base + 3.0:+.4f}%)")
                    if t_sd and t_su:
                        update_task_sibling_id(t_sd["id"], t_su["id"])
                        update_task_sibling_id(t_su["id"], t_sd["id"])
                    new_tasks = [t for t in (t_buy, t_sd, t_su) if t]
                else:
                    t_buy = add_fn(symbol, "DOWN", base - 2.5, "BUY",
                                   f"BUY lại nếu x giảm thêm 2.5% (tới {base - 2.5:+.4f}%)",
                                   sell_origin="SELL_UP")
                    t_sd = add_fn(symbol, "DOWN", base - 2.0, "SELL",
                                  f"SELL (stop-loss) nếu x giảm thêm 2% (tới {base - 2.0:+.4f}%)")
                    t_su = add_fn(symbol, "UP", base + 3.0, "SELL",
                                  f"SELL (take-profit) nếu x tăng 3% (tới {base + 3.0:+.4f}%)")
                    if t_sd and t_su:
                        update_task_sibling_id(t_sd["id"], t_su["id"])
                        update_task_sibling_id(t_su["id"], t_sd["id"])
                    new_tasks = [t for t in (t_buy, t_sd, t_su) if t]

                triggered.append(task)
                spawned.extend(new_tasks)
                triggered_any = True
                break
        if not triggered_any:
            break

    return {
        "section_id": section_id,
        "current_pct": current_pct,
        "delta_pct": delta_pct,
        "triggered": triggered,
        "spawned": spawned,
    }


def process_symbol_price(symbol: str, new_x: float) -> dict[str, Any]:
    """
    Broadcast price update to ALL sections of a symbol.
    Also records price history.
    """
    from .store import load_sections, add_price_history

    if new_x <= 0:
        return {"error": "Price must be > 0"}

    sections = load_sections(symbol)
    if not sections:
        return {"error": f"No sections found for {symbol}. Create a section first."}

    add_price_history(symbol, new_x)

    results = []
    for sec in sections:
        r = _process_section_price(
            sec["id"], sec["symbol"], sec["x0"],
            sec["current_pct"], new_x,
        )
        r["section_name"] = sec["name"]
        results.append(r)

    total_triggered = sum(len(r["triggered"]) for r in results)
    return {
        "symbol": symbol,
        "price": new_x,
        "sections_updated": len(results),
        "total_triggered": total_triggered,
        "results": results,
    }


def delete_engine_cmd(symbol: str) -> dict[str, Any]:
    from .store import delete_engine
    delete_engine(symbol)
    return {"ok": True, "symbol": symbol}


def get_price_history(symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    from .store import load_price_history
    return load_price_history(symbol, limit)
