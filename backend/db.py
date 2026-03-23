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
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
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


# --------------- Task Engine State ---------------

def load_task_engine_state(symbol: str) -> dict[str, Any] | None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "SELECT symbol, x0, current_x, current_pct, seeded FROM crypto_task_engine_state WHERE UPPER(symbol) = UPPER(%s)",
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
            }
    except Exception as e:
        logger.warning("db load_task_engine_state: %s", e)
        return None


def save_task_engine_state(symbol: str, state: dict[str, Any]) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_engine_state (symbol, x0, current_x, current_pct, seeded, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE SET
                     x0 = EXCLUDED.x0,
                     current_x = EXCLUDED.current_x,
                     current_pct = EXCLUDED.current_pct,
                     seeded = EXCLUDED.seeded,
                     updated_at = EXCLUDED.updated_at""",
                (
                    state["symbol"],
                    state["x0"],
                    state["current_x"],
                    state["current_pct"],
                    state["seeded"],
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
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)",
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
                })
    except Exception as e:
        logger.warning("db load_task_queue: %s", e)
    return out


def add_task_to_queue(symbol: str, direction: str, target_pct: float,
                      action: str, note: str,
                      sibling_id: int | None = None) -> dict[str, Any] | None:
    if target_pct < -98 or target_pct > 98:
        return None
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO crypto_task_queue (symbol, direction, target_pct, action, note, sibling_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (symbol.strip().upper(), direction, target_pct, action, note, sibling_id),
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
                    task_id: int | None = None) -> None:
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """INSERT INTO crypto_task_passed (symbol, task_id, direction, action, target_pct, hit_pct, hit_price, note, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol.strip().upper(), task_id, direction, action, target_pct, hit_pct, hit_price, note,
                 datetime.now(UTC7).replace(tzinfo=None)),
            )
    except Exception as e:
        logger.warning("db add_passed_task: %s", e)


def load_passed_tasks(symbol: str) -> list[dict[str, Any]]:
    out = []
    try:
        init_schema()
        with _cursor() as cur:
            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id
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
                "SELECT symbol, x0, current_x, current_pct, seeded FROM crypto_task_engine_state WHERE UPPER(symbol) = UPPER(%s)",
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
                }

            cur.execute(
                "SELECT id, symbol, direction, target_pct, action, note, sibling_id FROM crypto_task_queue WHERE UPPER(symbol) = UPPER(%s)",
                (sym,),
            )
            for row in cur.fetchall():
                result["tasks"].append({
                    "id": row[0], "symbol": row[1], "direction": row[2],
                    "target_pct": float(row[3]), "action": row[4],
                    "note": row[5] or "", "sibling_id": row[6],
                })

            cur.execute(
                """SELECT id, symbol, direction, action, target_pct, hit_pct, hit_price, note, created_at, task_id
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
