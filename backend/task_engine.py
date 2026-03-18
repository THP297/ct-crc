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
) -> list[dict]:
    """Create two tasks and link them as siblings."""
    t1 = add_fn(symbol, t1_dir, t1_target, t1_action, t1_note)
    t2 = add_fn(symbol, t2_dir, t2_target, t2_action, t2_note)

    if t1 and t2:
        update_sibling_fn(t1["id"], t2["id"])
        update_sibling_fn(t2["id"], t1["id"])
        t1["sibling_id"] = t2["id"]
        t2["sibling_id"] = t1["id"]

    return [t for t in (t1, t2) if t]


def _cancel_sibling(symbol: str, triggered_task: dict, current_pct: float,
                    current_x: float, tasks: list[dict]) -> None:
    """Close the sibling of a triggered task."""
    from .store import remove_task_from_queue, add_closed_task

    sibling_id = triggered_task.get("sibling_id")
    if not sibling_id:
        return

    sibling = next((t for t in tasks if t["id"] == sibling_id), None)
    if sibling is None:
        return

    if sibling["action"] == "BUY":
        return

    remove_task_from_queue(sibling_id)
    add_closed_task(
        symbol=symbol,
        closed_task_id=sibling_id,
        sibling_triggered_id=triggered_task["id"],
        direction=sibling["direction"],
        action=sibling["action"],
        target_pct=sibling["target_pct"],
        at_pct=current_pct,
        at_price=current_x,
        reason=f"Sibling #{triggered_task['id']} [{triggered_task['direction']}] triggered",
        note=sibling.get("note", ""),
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
                )

                _cancel_sibling(symbol, task, current_pct, new_x, tasks)

                new_tasks = _spawn_after_trigger(
                    symbol, task["direction"], task["action"],
                    current_pct, add_task_to_queue, update_task_sibling_id,
                )
                triggered.append(task)
                spawned.extend(new_tasks)
                triggered_any = True

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
    add_fn,
    update_sibling_fn,
) -> list[dict]:
    """
    Spawn tasks after trigger.
    BUY trigger → no spawn
    SELL + DOWN → DOWN/BUY -3% ↔ DOWN/SELL -2%
    SELL + UP   → t1: DOWN/BUY -2.5% (no sibling) | t2: DOWN/SELL -2% ↔ t3: UP/SELL +3%
    """
    base = current_pct

    if action == "BUY":
        return []

    if direction == "DOWN":
        buy_t = base - 3.0
        sell_t = base - 2.0
        return _spawn_pair(
            symbol,
            "DOWN", buy_t, "BUY",
            f"BUY lại nếu x giảm thêm 3% (tới {buy_t:+.4f}%)",
            "DOWN", sell_t, "SELL",
            f"SELL nếu x giảm thêm 2% (tới {sell_t:+.4f}%)",
            add_fn, update_sibling_fn,
        )

    # direction == "UP" → 3 tasks
    t1 = add_fn(symbol, "DOWN", base - 2.5, "BUY",
                f"BUY lại nếu x giảm thêm 2.5% (tới {base - 2.5:+.4f}%)")
    t2 = add_fn(symbol, "DOWN", base - 2.0, "SELL",
                f"SELL (stop-loss) nếu x giảm thêm 2% (tới {base - 2.0:+.4f}%)")
    t3 = add_fn(symbol, "UP", base + 3.0, "SELL",
                f"SELL (take-profit) nếu x tăng 3% (tới {base + 3.0:+.4f}%)")
    if t2 and t3:
        update_sibling_fn(t2["id"], t3["id"])
        update_sibling_fn(t3["id"], t2["id"])
        t2["sibling_id"] = t3["id"]
        t3["sibling_id"] = t2["id"]
    return [t for t in (t1, t2, t3) if t]


def init_engine(symbol: str, x0: float) -> dict[str, Any]:
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
    )

    if x0 <= 0:
        return {"error": "Base price must be > 0"}

    clear_task_queue_for_symbol(symbol)
    clear_passed_tasks_for_symbol(symbol)
    clear_closed_tasks_for_symbol(symbol)

    state = {
        "symbol": symbol,
        "x0": x0,
        "current_x": x0,
        "current_pct": 0.0,
        "seeded": True,
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
    from .store import (
        load_task_engine_state, load_task_queue,
        load_passed_tasks, load_closed_tasks,
    )

    state = load_task_engine_state(symbol)
    if state is None:
        return {
            "state": None, "up_tasks": [], "down_tasks": [],
            "passed_tasks": [], "closed_tasks": [],
        }

    tasks = load_task_queue(symbol)
    passed = load_passed_tasks(symbol)
    closed = load_closed_tasks(symbol)

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
        "passed_tasks": passed,
        "closed_tasks": closed,
    }


def get_all_engine_symbols() -> list[str]:
    from .store import load_all_task_engine_symbols
    return load_all_task_engine_symbols()
