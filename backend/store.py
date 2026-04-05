import json
import logging
import os
from datetime import datetime
from typing import Any

from .config import DATA_DIR, UTC7

logger = logging.getLogger(__name__)

TASK_ENGINE_STATE_FILE = DATA_DIR / "task_engine_state.json"
TASK_QUEUE_FILE = DATA_DIR / "task_queue.json"
TASK_PASSED_FILE = DATA_DIR / "task_passed.json"
TASK_CLOSED_FILE = DATA_DIR / "task_closed.json"

_task_queue_id_counter = 0


def _use_db() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_file(path) -> Any:
    _ensure_dir()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("_load_json_file %s: %s", path, e)
        return None


def _save_json_file(path, data: Any) -> None:
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --------------- Task Engine State ---------------

def load_task_engine_state(symbol: str) -> dict[str, Any] | None:
    if _use_db():
        from .db import load_task_engine_state as _load
        return _load(symbol)
    data = _load_json_file(TASK_ENGINE_STATE_FILE)
    if not data or not isinstance(data, dict):
        return None
    return data.get(symbol.strip().upper())


def save_task_engine_state(symbol: str, state: dict[str, Any]) -> None:
    if _use_db():
        from .db import save_task_engine_state as _save
        return _save(symbol, state)
    data = _load_json_file(TASK_ENGINE_STATE_FILE) or {}
    data[symbol.strip().upper()] = state
    _save_json_file(TASK_ENGINE_STATE_FILE, data)


def load_all_task_engine_symbols() -> list[str]:
    if _use_db():
        from .db import load_all_task_engine_symbols as _load
        return _load()
    data = _load_json_file(TASK_ENGINE_STATE_FILE)
    if not data or not isinstance(data, dict):
        return []
    return sorted(data.keys())


# --------------- Task Queue ---------------

def load_task_queue(symbol: str) -> list[dict[str, Any]]:
    if _use_db():
        from .db import load_task_queue as _load
        return _load(symbol)
    data = _load_json_file(TASK_QUEUE_FILE)
    if not data or not isinstance(data, list):
        return []
    sym = symbol.strip().upper()
    return [t for t in data if (t.get("symbol") or "").upper() == sym]


def add_task_to_queue(symbol: str, direction: str, target_pct: float,
                      action: str, note: str,
                      sibling_id: int | None = None,
                      sell_origin: str = "") -> dict[str, Any] | None:
    if target_pct < -98 or target_pct > 98:
        return None
    if _use_db():
        from .db import add_task_to_queue as _add
        return _add(symbol, direction, target_pct, action, note, sibling_id, sell_origin)
    global _task_queue_id_counter
    data = _load_json_file(TASK_QUEUE_FILE) or []
    max_id = max((t.get("id", 0) for t in data), default=0)
    _task_queue_id_counter = max(max_id, _task_queue_id_counter) + 1
    task = {
        "id": _task_queue_id_counter,
        "symbol": symbol.strip().upper(),
        "direction": direction,
        "target_pct": target_pct,
        "action": action,
        "note": note,
        "sibling_id": sibling_id,
        "sell_origin": sell_origin,
    }
    data.append(task)
    _save_json_file(TASK_QUEUE_FILE, data)
    return task


def update_task_sibling_id(task_id: int, sibling_id: int) -> None:
    if _use_db():
        from .db import update_task_sibling_id as _update
        return _update(task_id, sibling_id)
    data = _load_json_file(TASK_QUEUE_FILE) or []
    for t in data:
        if t.get("id") == task_id:
            t["sibling_id"] = sibling_id
            break
    _save_json_file(TASK_QUEUE_FILE, data)


def remove_task_from_queue(task_id: int) -> None:
    if _use_db():
        from .db import remove_task_from_queue as _remove
        return _remove(task_id)
    data = _load_json_file(TASK_QUEUE_FILE) or []
    data = [t for t in data if t.get("id") != task_id]
    _save_json_file(TASK_QUEUE_FILE, data)


def clear_task_queue_for_symbol(symbol: str) -> None:
    if _use_db():
        from .db import clear_task_queue_for_symbol as _clear
        return _clear(symbol)
    data = _load_json_file(TASK_QUEUE_FILE) or []
    sym = symbol.strip().upper()
    data = [t for t in data if (t.get("symbol") or "").upper() != sym]
    _save_json_file(TASK_QUEUE_FILE, data)


# --------------- Passed Tasks ---------------

def add_passed_task(symbol: str, direction: str, action: str, target_pct: float,
                    hit_pct: float, hit_price: float, note: str,
                    task_id: int | None = None,
                    sell_origin: str = "") -> None:
    if _use_db():
        from .db import add_passed_task as _add
        return _add(symbol, direction, action, target_pct, hit_pct, hit_price, note,
                    task_id=task_id, sell_origin=sell_origin)
    data = _load_json_file(TASK_PASSED_FILE) or []
    data.insert(0, {
        "symbol": symbol.strip().upper(),
        "task_id": task_id,
        "direction": direction,
        "action": action,
        "target_pct": target_pct,
        "hit_pct": hit_pct,
        "hit_price": hit_price,
        "note": note,
        "sell_origin": sell_origin,
        "at": datetime.now(UTC7).strftime("%Y-%m-%d %H:%M:%S"),
    })
    data = data[:500]
    _save_json_file(TASK_PASSED_FILE, data)


def load_passed_tasks(symbol: str) -> list[dict[str, Any]]:
    if _use_db():
        from .db import load_passed_tasks as _load
        return _load(symbol)
    data = _load_json_file(TASK_PASSED_FILE) or []
    sym = symbol.strip().upper()
    return [t for t in data if (t.get("symbol") or "").upper() == sym][:200]


def clear_passed_tasks_for_symbol(symbol: str) -> None:
    if _use_db():
        from .db import clear_passed_tasks_for_symbol as _clear
        return _clear(symbol)
    data = _load_json_file(TASK_PASSED_FILE) or []
    sym = symbol.strip().upper()
    data = [t for t in data if (t.get("symbol") or "").upper() != sym]
    _save_json_file(TASK_PASSED_FILE, data)


# --------------- Closed Tasks (sibling cancelled) ---------------

def add_closed_task(symbol: str, closed_task_id: int,
                    sibling_triggered_id: int, direction: str, action: str,
                    target_pct: float, at_pct: float, at_price: float,
                    reason: str, note: str) -> None:
    if _use_db():
        from .db import add_closed_task as _add
        return _add(symbol, closed_task_id, sibling_triggered_id, direction,
                     action, target_pct, at_pct, at_price, reason, note)
    data = _load_json_file(TASK_CLOSED_FILE) or []
    data.insert(0, {
        "symbol": symbol.strip().upper(),
        "closed_task_id": closed_task_id,
        "sibling_triggered_id": sibling_triggered_id,
        "direction": direction,
        "action": action,
        "target_pct": target_pct,
        "at_pct": at_pct,
        "at_price": at_price,
        "reason": reason,
        "note": note,
        "at": datetime.now(UTC7).strftime("%Y-%m-%d %H:%M:%S"),
    })
    data = data[:500]
    _save_json_file(TASK_CLOSED_FILE, data)


def load_closed_tasks(symbol: str) -> list[dict[str, Any]]:
    if _use_db():
        from .db import load_closed_tasks as _load
        return _load(symbol)
    data = _load_json_file(TASK_CLOSED_FILE) or []
    sym = symbol.strip().upper()
    return [t for t in data if (t.get("symbol") or "").upper() == sym][:200]


def clear_closed_tasks_for_symbol(symbol: str) -> None:
    if _use_db():
        from .db import clear_closed_tasks_for_symbol as _clear
        return _clear(symbol)
    data = _load_json_file(TASK_CLOSED_FILE) or []
    sym = symbol.strip().upper()
    data = [t for t in data if (t.get("symbol") or "").upper() != sym]
    _save_json_file(TASK_CLOSED_FILE, data)


# --------------- Live Prices ---------------

LIVE_PRICES_FILE = DATA_DIR / "live_prices.json"


def save_live_prices(prices: dict[str, float]) -> None:
    if not prices:
        return
    if _use_db():
        from .db import save_live_prices as _save
        return _save(prices)
    data = _load_json_file(LIVE_PRICES_FILE) or {}
    data.update({k.strip().upper(): v for k, v in prices.items()})
    _save_json_file(LIVE_PRICES_FILE, data)


def load_live_prices() -> dict[str, float]:
    if _use_db():
        from .db import load_live_prices as _load
        return _load()
    data = _load_json_file(LIVE_PRICES_FILE)
    if not data or not isinstance(data, dict):
        return {}
    return {k: float(v) for k, v in data.items()}


# --------------- Batched Info (single DB connection) ---------------

def load_engine_info_batched(symbol: str) -> dict[str, Any]:
    if _use_db():
        from .db import load_engine_info_batched as _load
        return _load(symbol)
    state = load_task_engine_state(symbol)
    tasks = load_task_queue(symbol)
    passed = load_passed_tasks(symbol)
    closed = load_closed_tasks(symbol)
    return {"state": state, "tasks": tasks, "passed": passed, "closed": closed}


# --------------- Settings ---------------

SETTINGS_FILE = DATA_DIR / "settings.json"


def load_settings(symbol: str) -> dict[str, Any] | None:
    if _use_db():
        from .db import load_settings as _load
        return _load(symbol)
    data = _load_json_file(SETTINGS_FILE)
    if not data or not isinstance(data, dict):
        return None
    return data.get(symbol.strip().upper())


def save_settings(symbol: str, sell_down_pct: float, sell_up_pct: float) -> None:
    if _use_db():
        from .db import save_settings as _save
        return _save(symbol, sell_down_pct, sell_up_pct)
    data = _load_json_file(SETTINGS_FILE) or {}
    data[symbol.strip().upper()] = {
        "symbol": symbol.strip().upper(),
        "sell_down_pct": sell_down_pct,
        "sell_up_pct": sell_up_pct,
    }
    _save_json_file(SETTINGS_FILE, data)


def load_all_settings() -> list[dict[str, Any]]:
    if _use_db():
        from .db import load_all_settings as _load
        return _load()
    data = _load_json_file(SETTINGS_FILE)
    if not data or not isinstance(data, dict):
        return []
    return sorted(data.values(), key=lambda s: s.get("symbol", ""))


def ensure_settings(symbol: str) -> dict[str, Any]:
    if _use_db():
        from .db import ensure_settings as _ensure
        return _ensure(symbol)
    existing = load_settings(symbol)
    if existing:
        return existing
    sym = symbol.strip().upper()
    default = {"symbol": sym, "sell_down_pct": 50.0, "sell_up_pct": 50.0}
    data = _load_json_file(SETTINGS_FILE) or {}
    data[sym] = default
    _save_json_file(SETTINGS_FILE, data)
    return default
