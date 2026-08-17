"""
MeteorBase webhook receiver - drop this into ANY of your child apps
(VEX, SkipIdeate, Oblivion, ...) so MeteorBase can route to it.

It refuses every request that is not authenticated by MeteorBase, so the
app can be safely exposed to the internet while still only ever serving
traffic that came through the gateway.

Env vars needed by the app:
    INTERNAL_SECRET     - same shared value as MeteorBase's INTERNAL_SECRET
    MB_WEBHOOK_SECRET   - the per-app secret from the MeteorBase dashboard

Run:  python webhook_receiver.py
"""
import os
from functools import wraps

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "change-me-shared-secret")
WEBHOOK_SECRET = os.environ.get("MB_WEBHOOK_SECRET", "change-me-app-secret")
MB_GATEWAY_URL = os.environ.get("MB_GATEWAY_URL", "http://localhost:5000")
APP_NAME = os.environ.get("APP_NAME", "oblivion")


def require_meteorbase(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Internal-Secret") != INTERNAL_SECRET:
            return jsonify({"error": "forbidden"}), 403
        if request.headers.get("X-Service-Secret") != WEBHOOK_SECRET:
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------
# EXAMPLE ROUTES - implement your real business logic here.
# Always scope data by the caller's MeteorBase user id.
# --------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "app": APP_NAME})


@app.route("/sessions", methods=["GET", "POST"])
@require_meteorbase
def sessions():
    user_id = request.headers.get("X-User-ID")
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        return jsonify({"created": True, "user": user_id, **body}), 201
    return jsonify({"sessions": [], "user": user_id})


@app.route("/stats", methods=["GET"])
@require_meteorbase
def stats():
    user_id = request.headers.get("X-User-ID")
    return jsonify({"focus_minutes": 0, "streak_days": 0, "user": user_id})


# --------------------------------------------------------------------------
# UPTIME HEARTBEAT - call this periodically (cron/APScheduler) so the
# MeteorBase dashboard shows this app as healthy.
# --------------------------------------------------------------------------
def ping_meteorbase():
    try:
        requests.post(
            f"{MB_GATEWAY_URL}/api/v1/apps/{APP_NAME}/heartbeat",
            headers={"X-Service-Secret": WEBHOOK_SECRET},
            json={"status": "ok", "latency_ms": 0, "details": {"app": APP_NAME}},
            timeout=10,
        )
    except Exception:
        pass


if __name__ == "__main__":
    ping_meteorbase()
    app.run(port=8001, debug=True)