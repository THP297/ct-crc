import atexit
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .config import UTC7

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_pool = None
_pool_lock = threading.Lock()


def _get_dsn() -> str:
    url = DATABASE_URL
    if not url:
        raise ValueError("DATABASE_URL is not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if "sslmode" not in url and "postgresql" in url:
        url = url + ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        from psycopg2.pool import ThreadedConnectionPool
        _pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=_get_dsn())
        atexit.register(_shutdown_pool)
        logger.info("DB connection pool created (min=1, max=5)")
        return _pool


def _shutdown_pool():
    global _pool
    if _pool is not None:
        try:
            _pool.closeall()
        except Exception:
            pass
        _pool = None


@contextmanager
def _cursor():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        pool.putconn(conn)


_schema_initialized = False


def init_schema() -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    _schema_initialized = True
    with _cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_task_engine_state (
                symbol VARCHAR(20) PRIMARY KEY,
                x0 NUMERIC NOT NULL,
                current_x NUMERIC NOT NULL,
                current_pct NUMERIC NOT NULL DEFAULT 0,
                seeded BOOLEAN NOT NULL DEFAULT FALSE,
                coin_qty NUMERIC NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        try:
            cur.execute("ALTER TABLE crypto_task_engine_state ADD COLUMN IF NOT EXISTS coin_qty NUMERIC NOT NULL DEFAULT 0")
        except Exception:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_task_queue (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                direction VARCHAR(4) NOT NULL,
                target_pct NUMERIC NOT NULL,
                action VARCHAR(10) NOT NULL DEFAULT 'BUY',
                note TEXT DEFAULT '',
                sibling_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_task_queue_symbol ON crypto_task_queue(symbol);")
        try:
            cur.execute("ALTER TABLE crypto_task_queue ADD COLUMN IF NOT EXISTS sibling_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE crypto_task_queue ADD COLUMN IF NOT EXISTS sell_origin VARCHAR(20) DEFAULT ''")
        except Exception:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_task_passed (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                direction VARCHAR(4) NOT NULL,
                action VARCHAR(10) NOT NULL DEFAULT 'BUY',
                target_pct NUMERIC NOT NULL,
                hit_pct NUMERIC NOT NULL,
                hit_price NUMERIC NOT NULL,
                note TEXT DEFAULT '',
                task_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_task_passed_symbol ON crypto_task_passed(symbol);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_task_passed_at ON crypto_task_passed(created_at DESC);")
        try:
            cur.execute("ALTER TABLE crypto_task_passed ADD COLUMN IF NOT EXISTS task_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE crypto_task_passed ADD COLUMN IF NOT EXISTS sell_origin VARCHAR(20) DEFAULT ''")
        except Exception:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_task_closed (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                closed_task_id INTEGER NOT NULL,
                sibling_triggered_id INTEGER NOT NULL,
                direction VARCHAR(4) NOT NULL,
                action VARCHAR(10) NOT NULL,
                target_pct NUMERIC NOT NULL,
                at_pct NUMERIC NOT NULL,
                at_price NUMERIC NOT NULL,
                reason TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_task_closed_symbol ON crypto_task_closed(symbol);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_task_closed_at ON crypto_task_closed(created_at DESC);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_live_prices (
                symbol VARCHAR(20) PRIMARY KEY,
                price NUMERIC NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_settings (
                symbol VARCHAR(20) PRIMARY KEY,
                sell_down_pct NUMERIC NOT NULL DEFAULT 50,
                sell_up_pct NUMERIC NOT NULL DEFAULT 50
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_sections (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                x0 NUMERIC NOT NULL,
                coin_qty NUMERIC NOT NULL DEFAULT 0,
                current_x NUMERIC NOT NULL,
                current_pct NUMERIC NOT NULL DEFAULT 0,
                seeded BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_sections_symbol ON crypto_sections(symbol);")

        try:
            cur.execute("ALTER TABLE crypto_task_queue ADD COLUMN IF NOT EXISTS section_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE crypto_task_passed ADD COLUMN IF NOT EXISTS section_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE crypto_task_closed ADD COLUMN IF NOT EXISTS section_id INTEGER")
        except Exception:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_price_history (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                price NUMERIC NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_price_history_symbol ON crypto_price_history(symbol);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_price_history_at ON crypto_price_history(created_at DESC);")


# --------------- Task Engine State ---------------

def load_task_engine_state(symbol: str) -> dict[str, Any] | None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT symbol, x0, current_x, current_pct, seeded, coin_qty FROM crypto_task_engine_state WHERE UPPER(symbol) = UPPER(%s)",
                (symbol.strip(),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "symbol": row[0],
                "x0": float(row[1]),
                "current_x": float(row[2]),
                "current_pct": float(row[3]),
                "seeded": bool(row[4]),
                "coin_qty": float(row[5]) if row[5] is not None else 0.0,
            }
    except Exception as e:
        logger.warning("db load_task_engine_state: %s", e)
        return None


def save_task_engine_state(symbol: str, state: dict[str, Any]) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_engine_state (symbol, x0, current_x, current_pct, seeded, coin_qty, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE SET
                     x0 = EXCLUDED.x0,
                     current_x = EXCLUDED.current_x,
                     current_pct = EXCLUDED.current_pct,
                     seeded = EXCLUDED.seeded,
                     coin_qty = EXCLUDED.coin_qty,
                     updated_at = EXCLUDED.updated_at""",
                (
                    state["symbol"],
                    state["x0"],
                    state["current_x"],
                    state["current_pct"],
                    state["seeded"],
                    state.get("coin_qty", 0),
                    datetime.now(UTC7).replace(tzinfo=None),
                ),
            )
    except Exception as e:
        logger.warning("db save_task_engine_state: %s", e)


def load_all_task_engine_symbols() -> list[str]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("SELECT symbol FROM crypto_task_engine_state ORDER BY symbol")
            out = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.warning("db load_all_task_engine_symbols: %s", e)
    return out


# --------------- Task Queue ---------------

def load_task_queue(symbol: str) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id, sell_origin FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)",
                (symbol.strip(),),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0],
                    "symbol": row[1],
                    "direction": row[2],
                    "target_pct": float(row[3]),
                    "action": row[4],
                    "note": row[5] or "",
                    "sibling_id": row[6],
                    "sell_origin": row[7] or "",
                })
    except Exception as e:
        logger.warning("db load_task_queue: %s", e)
    return out


def add_task_to_queue(symbol: str, direction: str, target_pct: float,
                      action: str, note: str,
                      sibling_id: int | None = None,
                      sell_origin: str = "") -> dict[str, Any] | None:
    if target_pct < -98 or target_pct > 98:
        return None
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO crypto_task_queue (symbol, direction, target_pct, action, note, sibling_id, sell_origin) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (symbol.strip().upper(), direction, target_pct, action, note, sibling_id, sell_origin),
            )
            row = cur.fetchone()
            return {
                "id": row[0],
                "symbol": symbol.strip().upper(),
                "direction": direction,
                "target_pct": target_pct,
                "action": action,
                "note": note,
                "sibling_id": sibling_id,
                "sell_origin": sell_origin,
            }
    except Exception as e:
        logger.warning("db add_task_to_queue: %s", e)
        return None


def update_task_sibling_id(task_id: int, sibling_id: int) -> None:
    try:
        with _cursor() as cur:
            cur.execute(
                "UPDATE crypto_task_queue SET sibling_id = %s WHERE id = %s",
                (sibling_id, task_id),
            )
    except Exception as e:
        logger.warning("db update_task_sibling_id: %s", e)


def remove_task_from_queue(task_id: int) -> None:
    try:
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_queue WHERE id = %s", (task_id,))
    except Exception as e:
        logger.warning("db remove_task_from_queue: %s", e)


def clear_task_queue_for_symbol(symbol: str) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)", (symbol.strip(),))
    except Exception as e:
        logger.warning("db clear_task_queue_for_symbol: %s", e)


# --------------- Passed Tasks ---------------

def add_passed_task(symbol: str, direction: str, action: str, target_pct: float,
                    hit_pct: float, hit_price: float, note: str,
                    task_id: int | None = None,
                    sell_origin: str = "") -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_passed (symbol, task_id, direction, action, target_pct, hit_pct, hit_price, note, sell_origin, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol.strip().upper(), task_id, direction, action, target_pct, hit_pct, hit_price, note,
                 sell_origin, datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_passed_task: %s", e)


def load_passed_tasks(symbol: str) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id, sell_origin
                   FROM crypto_task_passed WHERE UPPER(symbol) = UPPER(%s) ORDER BY created_at DESC LIMIT 200""",
                (symbol.strip(),),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0],
                    "symbol": row[1],
                    "direction": row[2],
                    "action": row[3],
                    "target_pct": float(row[4]),
                    "hit_pct": float(row[5]),
                    "hit_price": float(row[6]),
                    "note": row[7] or "",
                    "at": row[8].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[8], "strftime") else str(row[8]),
                    "task_id": row[9] if len(row) > 9 else None,
                    "sell_origin": row[10] or "" if len(row) > 10 else "",
                })
    except Exception as e:
        logger.warning("db load_passed_tasks: %s", e)
    return out


def clear_passed_tasks_for_symbol(symbol: str) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_passed WHERE UPPER(symbol) = UPPER(%s)", (symbol.strip(),))
    except Exception as e:
        logger.warning("db clear_passed_tasks_for_symbol: %s", e)


# --------------- Closed Tasks (sibling cancelled) ---------------

def add_closed_task(symbol: str, closed_task_id: int,
                    sibling_triggered_id: int, direction: str, action: str,
                    target_pct: float, at_pct: float, at_price: float,
                    reason: str, note: str) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_closed
                   (symbol, closed_task_id, sibling_triggered_id, direction, action,
                    target_pct, at_pct, at_price, reason, note, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol.strip().upper(), closed_task_id, sibling_triggered_id,
                 direction, action, target_pct, at_pct, at_price, reason, note,
                 datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_closed_task: %s", e)


def load_closed_tasks(symbol: str) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """SELECT id, symbol, closed_task_id, sibling_triggered_id,
                          direction, action, target_pct, at_pct, at_price,
                          reason, note, created_at
                   FROM crypto_task_closed
                   WHERE UPPER(symbol) = UPPER(%s)
                   ORDER BY created_at DESC LIMIT 200""",
                (symbol.strip(),),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0],
                    "symbol": row[1],
                    "closed_task_id": row[2],
                    "sibling_triggered_id": row[3],
                    "direction": row[4],
                    "action": row[5],
                    "target_pct": float(row[6]),
                    "at_pct": float(row[7]),
                    "at_price": float(row[8]),
                    "reason": row[9] or "",
                    "note": row[10] or "",
                    "at": row[11].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[11], "strftime") else str(row[11]),
                })
    except Exception as e:
        logger.warning("db load_closed_tasks: %s", e)
    return out


def clear_closed_tasks_for_symbol(symbol: str) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_closed WHERE UPPER(symbol) = UPPER(%s)", (symbol.strip(),))
    except Exception as e:
        logger.warning("db clear_closed_tasks_for_symbol: %s", e)


# --------------- Live Prices ---------------

def save_live_prices(prices: dict[str, float]) -> None:
    if not prices:
        return
    try:
        init_schema()
        now = datetime.now(UTC7).replace(tzinfo=None)
        values = [(s.strip().upper(), p, now) for s, p in prices.items()]
        with _cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                """INSERT INTO crypto_live_prices (symbol, price, updated_at)
                   VALUES %s
                   ON CONFLICT (symbol) DO UPDATE SET
                     price = EXCLUDED.price,
                     updated_at = EXCLUDED.updated_at""",
                values,
                template="(%s, %s, %s)",
            )
    except Exception as e:
        logger.warning("db save_live_prices: %s", e)


def load_live_prices() -> dict[str, float]:
    out = {}
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("SELECT symbol, price FROM crypto_live_prices")
            for row in cur.fetchall():
                out[row[0]] = float(row[1])
    except Exception as e:
        logger.warning("db load_live_prices: %s", e)
    return out


# --------------- Batched info query (single connection) ---------------

def load_engine_info_batched(symbol: str) -> dict[str, Any]:
    """Load state + queue + passed + closed in a single DB connection."""
    result: dict[str, Any] = {
        "state": None, "tasks": [], "passed": [], "closed": [],
    }
    try:
        init_schema()
        sym = symbol.strip()
        with _cursor() as cur:
            cur.execute(
                "SELECT symbol, x0, current_x, current_pct, seeded, coin_qty FROM crypto_task_engine_state WHERE UPPER(symbol) = UPPER(%s)",
                (sym,),
            )
            row = cur.fetchone()
            if row:
                result["state"] = {
                    "symbol": row[0],
                    "x0": float(row[1]),
                    "current_x": float(row[2]),
                    "current_pct": float(row[3]),
                    "seeded": bool(row[4]),
                    "coin_qty": float(row[5]) if row[5] is not None else 0.0,
                }

            cur.execute(
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id, sell_origin FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)",
                (sym,),
            )
            for row in cur.fetchall():
                result["tasks"].append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "target_pct": float(row[3]), "action": row[4],
                    "note": row[5] or "", "sibling_id": row[6],
                    "sell_origin": row[7] or "",
                })

            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id, sell_origin
                   FROM crypto_task_passed WHERE UPPER(symbol) = UPPER(%s) ORDER BY created_at DESC LIMIT 200""",
                (sym,),
            )
            for row in cur.fetchall():
                result["passed"].append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "action": row[3], "target_pct": float(row[4]),
                    "hit_pct": float(row[5]), "hit_price": float(row[6]),
                    "note": row[7] or "",
                    "at": row[8].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[8], "strftime") else str(row[8]),
                    "task_id": row[9] if len(row) > 9 else None,
                    "sell_origin": row[10] or "" if len(row) > 10 else "",
                })

            cur.execute(
                """SELECT id, symbol, closed_task_id, sibling_triggered_id,
                          direction, action, target_pct, at_pct, at_price,
                          reason, note, created_at
                   FROM crypto_task_closed WHERE UPPER(symbol) = UPPER(%s)
                   ORDER BY created_at DESC LIMIT 200""",
                (sym,),
            )
            for row in cur.fetchall():
                result["closed"].append({
                    "id": row[0], "symbol": row[1],
                    "closed_task_id": row[2], "sibling_triggered_id": row[3],
                    "direction": row[4], "action": row[5],
                    "target_pct": float(row[6]), "at_pct": float(row[7]),
                    "at_price": float(row[8]),
                    "reason": row[9] or "", "note": row[10] or "",
                    "at": row[11].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[11], "strftime") else str(row[11]),
                })
    except Exception as e:
        logger.warning("db load_engine_info_batched: %s", e)
    return result


# --------------- Settings ---------------

def load_settings(symbol: str) -> dict[str, Any] | None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT symbol, sell_down_pct, sell_up_pct FROM crypto_settings WHERE UPPER(symbol) = UPPER(%s)",
                (symbol.strip(),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "symbol": row[0],
                "sell_down_pct": float(row[1]),
                "sell_up_pct": float(row[2]),
            }
    except Exception as e:
        logger.warning("db load_settings: %s", e)
        return None


def save_settings(symbol: str, sell_down_pct: float, sell_up_pct: float) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_settings (symbol, sell_down_pct, sell_up_pct)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE SET
                     sell_down_pct = EXCLUDED.sell_down_pct,
                     sell_up_pct = EXCLUDED.sell_up_pct""",
                (symbol.strip().upper(), sell_down_pct, sell_up_pct),
            )
    except Exception as e:
        logger.warning("db save_settings: %s", e)


def load_all_settings() -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("SELECT symbol, sell_down_pct, sell_up_pct FROM crypto_settings ORDER BY symbol")
            for row in cur.fetchall():
                out.append({
                    "symbol": row[0],
                    "sell_down_pct": float(row[1]),
                    "sell_up_pct": float(row[2]),
                })
    except Exception as e:
        logger.warning("db load_all_settings: %s", e)
    return out


def ensure_settings(symbol: str) -> dict[str, Any]:
    """Create default settings (50/50) if none exist for the symbol."""
    existing = load_settings(symbol)
    if existing:
        return existing
    save_settings(symbol, 50.0, 50.0)
    return {"symbol": symbol.strip().upper(), "sell_down_pct": 50.0, "sell_up_pct": 50.0}


# --------------- Sections ---------------

def create_section(symbol: str, name: str, x0: float, coin_qty: float) -> dict[str, Any] | None:
    try:
        init_schema()
        now = datetime.now(UTC7).replace(tzinfo=None)
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_sections (name, symbol, x0, coin_qty, current_x, current_pct, seeded, created_at)
                   VALUES (%s, %s, %s, %s, %s, 0, TRUE, %s) RETURNING id""",
                (name, symbol.strip().upper(), x0, coin_qty, x0, now),
            )
            row = cur.fetchone()
            return {
                "id": row[0], "name": name, "symbol": symbol.strip().upper(),
                "x0": x0, "coin_qty": coin_qty, "current_x": x0,
                "current_pct": 0.0, "seeded": True,
            }
    except Exception as e:
        logger.warning("db create_section: %s", e)
        return None


def load_sections(symbol: str | None = None) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            if symbol:
                cur.execute(
                    "SELECT id, name, symbol, x0, coin_qty, current_x, current_pct, seeded FROM crypto_sections WHERE UPPER(symbol) = UPPER(%s) ORDER BY id",
                    (symbol.strip(),),
                )
            else:
                cur.execute("SELECT id, name, symbol, x0, coin_qty, current_x, current_pct, seeded FROM crypto_sections ORDER BY symbol, id")
            for row in cur.fetchall():
                out.append({
                    "id": row[0], "name": row[1], "symbol": row[2],
                    "x0": float(row[3]), "coin_qty": float(row[4]),
                    "current_x": float(row[5]), "current_pct": float(row[6]),
                    "seeded": bool(row[7]),
                })
    except Exception as e:
        logger.warning("db load_sections: %s", e)
    return out


def load_section(section_id: int) -> dict[str, Any] | None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT id, name, symbol, x0, coin_qty, current_x, current_pct, seeded FROM crypto_sections WHERE id = %s",
                (section_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "id": row[0], "name": row[1], "symbol": row[2],
                "x0": float(row[3]), "coin_qty": float(row[4]),
                "current_x": float(row[5]), "current_pct": float(row[6]),
                "seeded": bool(row[7]),
            }
    except Exception as e:
        logger.warning("db load_section: %s", e)
        return None


def save_section_state(section_id: int, current_x: float, current_pct: float) -> None:
    try:
        with _cursor() as cur:
            cur.execute(
                "UPDATE crypto_sections SET current_x = %s, current_pct = %s WHERE id = %s",
                (current_x, current_pct, section_id),
            )
    except Exception as e:
        logger.warning("db save_section_state: %s", e)


def delete_section_db(section_id: int) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_queue WHERE section_id = %s", (section_id,))
            cur.execute("DELETE FROM crypto_task_passed WHERE section_id = %s", (section_id,))
            cur.execute("DELETE FROM crypto_task_closed WHERE section_id = %s", (section_id,))
            cur.execute("DELETE FROM crypto_sections WHERE id = %s", (section_id,))
    except Exception as e:
        logger.warning("db delete_section_db: %s", e)


def load_task_queue_by_section(section_id: int) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id, sell_origin, section_id FROM crypto_task_queue WHERE section_id = %s",
                (section_id,),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "target_pct": float(row[3]), "action": row[4],
                    "note": row[5] or "", "sibling_id": row[6],
                    "sell_origin": row[7] or "", "section_id": row[8],
                })
    except Exception as e:
        logger.warning("db load_task_queue_by_section: %s", e)
    return out


def add_task_to_queue_for_section(section_id: int, symbol: str, direction: str,
                                   target_pct: float, action: str, note: str,
                                   sibling_id: int | None = None,
                                   sell_origin: str = "") -> dict[str, Any] | None:
    if target_pct < -98 or target_pct > 98:
        return None
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO crypto_task_queue (symbol, direction, target_pct, action, note, sibling_id, sell_origin, section_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (symbol.strip().upper(), direction, target_pct, action, note, sibling_id, sell_origin, section_id),
            )
            row = cur.fetchone()
            return {
                "id": row[0], "symbol": symbol.strip().upper(),
                "direction": direction, "target_pct": target_pct,
                "action": action, "note": note, "sibling_id": sibling_id,
                "sell_origin": sell_origin, "section_id": section_id,
            }
    except Exception as e:
        logger.warning("db add_task_to_queue_for_section: %s", e)
        return None


def add_passed_task_for_section(section_id: int, symbol: str, direction: str,
                                 action: str, target_pct: float, hit_pct: float,
                                 hit_price: float, note: str,
                                 task_id: int | None = None,
                                 sell_origin: str = "") -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_passed (symbol, task_id, direction, action, target_pct, hit_pct, hit_price, note, sell_origin, section_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol.strip().upper(), task_id, direction, action, target_pct,
                 hit_pct, hit_price, note, sell_origin, section_id,
                 datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_passed_task_for_section: %s", e)


def load_passed_tasks_by_section(section_id: int) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id, sell_origin, section_id
                   FROM crypto_task_passed WHERE section_id = %s ORDER BY created_at DESC LIMIT 200""",
                (section_id,),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "action": row[3], "target_pct": float(row[4]),
                    "hit_pct": float(row[5]), "hit_price": float(row[6]),
                    "note": row[7] or "",
                    "at": row[8].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[8], "strftime") else str(row[8]),
                    "task_id": row[9], "sell_origin": row[10] or "",
                    "section_id": row[11],
                })
    except Exception as e:
        logger.warning("db load_passed_tasks_by_section: %s", e)
    return out


def add_closed_task_for_section(section_id: int, symbol: str, closed_task_id: int,
                                 sibling_triggered_id: int | None, direction: str,
                                 action: str, target_pct: float, at_pct: float,
                                 at_price: float, reason: str, note: str) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_closed
                   (symbol, closed_task_id, sibling_triggered_id, direction, action,
                    target_pct, at_pct, at_price, reason, note, section_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol.strip().upper(), closed_task_id, sibling_triggered_id,
                 direction, action, target_pct, at_pct, at_price, reason, note,
                 section_id, datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_closed_task_for_section: %s", e)


def load_closed_tasks_by_section(section_id: int) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """SELECT id, symbol, closed_task_id, sibling_triggered_id,
                          direction, action, target_pct, at_pct, at_price,
                          reason, note, created_at, section_id
                   FROM crypto_task_closed WHERE section_id = %s
                   ORDER BY created_at DESC LIMIT 200""",
                (section_id,),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0], "symbol": row[1],
                    "closed_task_id": row[2], "sibling_triggered_id": row[3],
                    "direction": row[4], "action": row[5],
                    "target_pct": float(row[6]), "at_pct": float(row[7]),
                    "at_price": float(row[8]),
                    "reason": row[9] or "", "note": row[10] or "",
                    "at": row[11].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[11], "strftime") else str(row[11]),
                    "section_id": row[12],
                })
    except Exception as e:
        logger.warning("db load_closed_tasks_by_section: %s", e)
    return out


def load_section_info_batched(section_id: int) -> dict[str, Any]:
    result: dict[str, Any] = {"section": None, "tasks": [], "passed": [], "closed": []}
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT id, name, symbol, x0, coin_qty, current_x, current_pct, seeded FROM crypto_sections WHERE id = %s",
                (section_id,),
            )
            row = cur.fetchone()
            if row:
                result["section"] = {
                    "id": row[0], "name": row[1], "symbol": row[2],
                    "x0": float(row[3]), "coin_qty": float(row[4]),
                    "current_x": float(row[5]), "current_pct": float(row[6]),
                    "seeded": bool(row[7]),
                }

            cur.execute(
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id, sell_origin, section_id FROM crypto_task_queue WHERE section_id = %s",
                (section_id,),
            )
            for row in cur.fetchall():
                result["tasks"].append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "target_pct": float(row[3]), "action": row[4],
                    "note": row[5] or "", "sibling_id": row[6],
                    "sell_origin": row[7] or "", "section_id": row[8],
                })

            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id, sell_origin, section_id
                   FROM crypto_task_passed WHERE section_id = %s ORDER BY created_at DESC LIMIT 200""",
                (section_id,),
            )
            for row in cur.fetchall():
                result["passed"].append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "action": row[3], "target_pct": float(row[4]),
                    "hit_pct": float(row[5]), "hit_price": float(row[6]),
                    "note": row[7] or "",
                    "at": row[8].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[8], "strftime") else str(row[8]),
                    "task_id": row[9], "sell_origin": row[10] or "",
                    "section_id": row[11],
                })

            cur.execute(
                """SELECT id, symbol, closed_task_id, sibling_triggered_id,
                          direction, action, target_pct, at_pct, at_price,
                          reason, note, created_at, section_id
                   FROM crypto_task_closed WHERE section_id = %s
                   ORDER BY created_at DESC LIMIT 200""",
                (section_id,),
            )
            for row in cur.fetchall():
                result["closed"].append({
                    "id": row[0], "symbol": row[1],
                    "closed_task_id": row[2], "sibling_triggered_id": row[3],
                    "direction": row[4], "action": row[5],
                    "target_pct": float(row[6]), "at_pct": float(row[7]),
                    "at_price": float(row[8]),
                    "reason": row[9] or "", "note": row[10] or "",
                    "at": row[11].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[11], "strftime") else str(row[11]),
                    "section_id": row[12],
                })
    except Exception as e:
        logger.warning("db load_section_info_batched: %s", e)
    return result


# --------------- Price History ---------------

def add_price_history(symbol: str, price: float) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO crypto_price_history (symbol, price, created_at) VALUES (%s, %s, %s)",
                (symbol.strip().upper(), price, datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_price_history: %s", e)


def load_price_history(symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT id, symbol, price, created_at FROM crypto_price_history WHERE UPPER(symbol) = UPPER(%s) ORDER BY created_at DESC LIMIT %s",
                (symbol.strip(), limit),
            )
            for row in cur.fetchall():
                out.append({
                    "id": row[0], "symbol": row[1], "price": float(row[2]),
                    "at": row[3].strftime("%Y-%m-%d %H:%M:%S") if hasattr(row[3], "strftime") else str(row[3]),
                })
    except Exception as e:
        logger.warning("db load_price_history: %s", e)
    return out


def delete_engine_db(symbol: str) -> None:
    """Delete all data for a symbol: sections, tasks, passed, closed, engine state, settings."""
    try:
        init_schema()
        sym = symbol.strip().upper()
        with _cursor() as cur:
            cur.execute("DELETE FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_task_passed WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_task_closed WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_sections WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_task_engine_state WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_settings WHERE UPPER(symbol) = UPPER(%s)", (sym,))
            cur.execute("DELETE FROM crypto_price_history WHERE UPPER(symbol) = UPPER(%s)", (sym,))
    except Exception as e:
        logger.warning("db delete_engine_db: %s", e)
