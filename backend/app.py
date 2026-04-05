import logging
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import runpy
    runpy.run_module("backend.app", run_name="__main__")
    sys.exit()

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request

from .config import FLASK_HOST, FLASK_PORT
from .fetcher import fetch_prices_dict

run_check = None
try:
    from .alert_checker import run_check as _run_check, start_background_checker
    run_check = _run_check
    start_background_checker()
except Exception as e:
    logging.warning("Background checker not started: %s", e)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        from flask import make_response
        r = make_response()
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Max-Age"] = "86400"
        return r


@app.route("/")
def index():
    return jsonify({
        "ok": True,
        "app": "crypto-currency-telegram",
        "endpoints": [
            "/api/price",
            "/api/check",
            "/api/task-engine/symbols",
            "/api/task-engine/init",
            "/api/task-engine/price",
            "/api/task-engine/info",
            "/api/task-engine/live-prices",
            "/api/task-engine/settings",
            "/api/task-engine/summary",
            "/api/task-engine/sections",
            "/api/task-engine/price-broadcast",
            "/api/task-engine/price-history",
        ],
    })


@app.route("/api/price")
def api_price():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400
    try:
        prices = fetch_prices_dict([symbol])
        if symbol not in prices:
            return jsonify({
                "error": f"Could not get price for {symbol}. Binance API failed. Try again later."
            }), 404
        return jsonify({"symbol": symbol, "price": prices[symbol]})
    except Exception as e:
        logging.exception("api/price: %s", e)
        return jsonify({"error": str(e)}), 500


# --------------- Task Engine API ---------------

@app.route("/api/task-engine/symbols")
def api_task_engine_symbols():
    from .task_engine import get_all_engine_symbols
    return jsonify({"symbols": get_all_engine_symbols()})


@app.route("/api/task-engine/init", methods=["POST"])
def api_task_engine_init():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    x0 = data.get("x0")
    if not symbol or x0 is None:
        return jsonify({"error": "symbol and x0 are required"}), 400
    try:
        x0 = float(x0)
    except (ValueError, TypeError):
        return jsonify({"error": "x0 must be a number"}), 400
    coin_qty = 0.0
    if data.get("coin_qty") is not None:
        try:
            coin_qty = float(data["coin_qty"])
        except (ValueError, TypeError):
            return jsonify({"error": "coin_qty must be a number"}), 400
    from .task_engine import init_engine
    result = init_engine(symbol, x0, coin_qty=coin_qty)
    if "error" in result:
        return jsonify(result), 400
    try:
        from .realtime_poller import poll_now
        poll_now()
    except Exception:
        pass
    return jsonify({"ok": True, **result})


@app.route("/api/task-engine/price", methods=["POST"])
def api_task_engine_price():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    price = data.get("price")
    if not symbol or price is None:
        return jsonify({"error": "symbol and price are required"}), 400
    try:
        price = float(str(price).replace(",", "").strip())
    except (ValueError, TypeError):
        return jsonify({"error": "price must be a number"}), 400
    from .task_engine import process_new_price
    result = process_new_price(symbol, price)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"ok": True, **result})


@app.route("/api/task-engine/info")
def api_task_engine_info():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    from .task_engine import get_engine_info
    return jsonify(get_engine_info(symbol))


@app.route("/api/task-engine/settings", methods=["GET"])
def api_task_engine_settings_get():
    from .store import load_all_settings
    return jsonify({"settings": load_all_settings()})


@app.route("/api/task-engine/settings", methods=["POST"])
def api_task_engine_settings_save():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    try:
        sell_down_pct = float(data.get("sell_down_pct", 50))
        sell_up_pct = float(data.get("sell_up_pct", 50))
    except (ValueError, TypeError):
        return jsonify({"error": "sell_down_pct and sell_up_pct must be numbers"}), 400
    if not (0 < sell_down_pct <= 100) or not (0 < sell_up_pct <= 100):
        return jsonify({"error": "Percentages must be between 0 and 100"}), 400
    from .store import save_settings
    save_settings(symbol, sell_down_pct, sell_up_pct)
    return jsonify({"ok": True, "symbol": symbol, "sell_down_pct": sell_down_pct, "sell_up_pct": sell_up_pct})


@app.route("/api/task-engine/live-prices")
def api_live_prices():
    from .realtime_poller import get_latest_prices
    try:
        prices = get_latest_prices()
    except Exception as e:
        logging.warning("live-prices: %s", e)
        prices = {}
    return jsonify(prices or {})


# --------------- Sections API ---------------

@app.route("/api/task-engine/sections", methods=["GET"])
def api_sections_list():
    symbol = (request.args.get("symbol") or "").strip().upper() or None
    from .task_engine import list_sections
    return jsonify({"sections": list_sections(symbol)})


@app.route("/api/task-engine/sections", methods=["POST"])
def api_sections_create():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    name = (data.get("name") or "").strip()
    x0 = data.get("x0")
    if not symbol or not name or x0 is None:
        return jsonify({"error": "symbol, name, and x0 are required"}), 400
    try:
        x0 = float(x0)
    except (ValueError, TypeError):
        return jsonify({"error": "x0 must be a number"}), 400
    coin_qty = 0.0
    if data.get("coin_qty") is not None:
        try:
            coin_qty = float(data["coin_qty"])
        except (ValueError, TypeError):
            return jsonify({"error": "coin_qty must be a number"}), 400
    from .task_engine import create_section
    result = create_section(symbol, name, x0, coin_qty)
    if "error" in result:
        return jsonify(result), 400
    try:
        from .realtime_poller import poll_now
        poll_now()
    except Exception:
        pass
    return jsonify({"ok": True, **result})


@app.route("/api/task-engine/sections/<int:section_id>", methods=["GET"])
def api_section_info(section_id):
    from .task_engine import get_section_info
    return jsonify(get_section_info(section_id))


@app.route("/api/task-engine/sections/<int:section_id>", methods=["DELETE"])
def api_section_delete(section_id):
    from .task_engine import delete_section_cmd
    result = delete_section_cmd(section_id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/task-engine/price-broadcast", methods=["POST"])
def api_price_broadcast():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    price = data.get("price")
    if not symbol or price is None:
        return jsonify({"error": "symbol and price are required"}), 400
    try:
        price = float(str(price).replace(",", "").strip())
    except (ValueError, TypeError):
        return jsonify({"error": "price must be a number"}), 400
    from .task_engine import process_symbol_price
    result = process_symbol_price(symbol, price)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"ok": True, **result})


@app.route("/api/task-engine/engine/<symbol>", methods=["DELETE"])
def api_delete_engine(symbol):
    symbol = symbol.strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    from .task_engine import delete_engine_cmd
    return jsonify(delete_engine_cmd(symbol))


@app.route("/api/task-engine/price-history")
def api_price_history():
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    limit = int(request.args.get("limit", 20))
    from .task_engine import get_price_history
    return jsonify({"history": get_price_history(symbol, limit)})


@app.route("/api/task-engine/summary")
def api_task_engine_summary():
    from .task_engine import list_sections, get_section_info
    from .store import load_settings, ensure_settings

    sections = list_sections()
    coins_map = {}
    for sec in sections:
        sym = sec["symbol"]
        coins_map.setdefault(sym, []).append(sec)

    result = []
    for sym in sorted(coins_map.keys()):
        settings = load_settings(sym) or ensure_settings(sym)
        sell_down_pct = settings.get("sell_down_pct", 50)
        sell_up_pct = settings.get("sell_up_pct", 50)

        sell_down_rows = []
        buy_down_rows = []
        sell_up_rows = []

        for sec in coins_map[sym]:
            info = get_section_info(sec["id"])
            all_tasks = info.get("up_tasks", []) + info.get("down_tasks", [])
            coin_qty = sec.get("coin_qty", 0)

            for t in all_tasks:
                row = {**t, "coin_qty": coin_qty, "section_name": sec["name"], "section_id": sec["id"]}
                if t["action"] == "SELL" and t["direction"] == "DOWN":
                    row["coins_to_trade"] = coin_qty * sell_down_pct / 100.0
                    row["target_price"] = sec["x0"] * (1 + t["target_pct"] / 100.0)
                    sell_down_rows.append(row)
                elif t["action"] == "SELL" and t["direction"] == "UP":
                    row["coins_to_trade"] = coin_qty * sell_up_pct / 100.0
                    row["target_price"] = sec["x0"] * (1 + t["target_pct"] / 100.0)
                    sell_up_rows.append(row)
                elif t["action"] == "BUY":
                    origin = t.get("sell_origin", "")
                    pct = sell_down_pct if origin != "SELL_UP" else sell_up_pct
                    row["coins_to_trade"] = coin_qty * pct / 100.0
                    row["target_price"] = sec["x0"] * (1 + t["target_pct"] / 100.0)
                    buy_down_rows.append(row)

        result.append({
            "symbol": sym,
            "sections": coins_map[sym],
            "settings": settings,
            "sell_down": sell_down_rows,
            "buy_down": buy_down_rows,
            "sell_up": sell_up_rows,
            "total_sell_down_coins": sum(r["coins_to_trade"] for r in sell_down_rows),
            "total_buy_down_coins": sum(r["coins_to_trade"] for r in buy_down_rows),
            "total_sell_up_coins": sum(r["coins_to_trade"] for r in sell_up_rows),
        })

    return jsonify({"summary": result})


@app.route("/api/check", methods=["GET", "POST"])
def api_run_check():
    try:
        if run_check is None:
            return jsonify({"ok": False, "error": "Checker not available"}), 500
        run_check()
        return jsonify({"ok": True, "message": "Check completed"})
    except Exception as e:
        logging.exception("api/check: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
