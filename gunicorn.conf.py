"""Gunicorn config. post_fork ensures WebSocket poller runs in worker after fork."""


def post_fork(server, worker):
    try:
        from backend.realtime_poller import start_poller
        start_poller()
    except Exception as e:
        import logging
        logging.warning("post_fork start_poller: %s", e)
