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
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        from flask import make_response
        r = make_response()
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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
    from .task_engine import init_engine
    result = init_engine(symbol, x0)
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


@app.route("/api/task-engine/live-prices")
def api_live_prices():
    from .realtime_poller import poll_now
    try:
        prices = poll_now()
    except Exception as e:
        logging.warning("live-prices poll: %s", e)
        from .realtime_poller import get_latest_prices
        prices = get_latest_prices()
    return jsonify(prices or {})


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
