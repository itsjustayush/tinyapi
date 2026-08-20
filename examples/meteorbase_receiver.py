"""Copy this file into a child Flask service and set the environment variables.

Required variables:
  INTERNAL_SECRET            Same value as MeteorBase's INTERNAL_SECRET.
  METEORBASE_SERVICE_SECRET  The one-time secret returned when the service is registered.
  METEORBASE_URL              Defaults to https://tinyapi-urjr.onrender.com.
"""
from __future__ import annotations

import os
from functools import wraps
from hmac import compare_digest

import requests
from flask import jsonify, request

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
SERVICE_SECRET = os.environ.get("METEORBASE_SERVICE_SECRET", "")
METEORBASE_URL = os.environ.get("METEORBASE_URL", "https://tinyapi-urjr.onrender.com").rstrip("/")


def require_meteorbase(view):
    """Reject direct or forged requests before the normal route executes."""
    @wraps(view)
    def guarded(*args, **kwargs):
        if not INTERNAL_SECRET or not SERVICE_SECRET:
            return jsonify({"error": "MeteorBase receiver is not configured"}), 503
        if not compare_digest(request.headers.get("X-Internal-Secret", ""), INTERNAL_SECRET):
            return jsonify({"error": "MeteorBase trust header required"}), 403
        if not compare_digest(request.headers.get("X-Service-Secret", ""), SERVICE_SECRET):
            return jsonify({"error": "Service trust header required"}), 403
        if not request.headers.get("X-User-ID"):
            return jsonify({"error": "Forwarded user identity required"}), 400
        return view(*args, **kwargs)
    return guarded


def ping_meteorbase(status="ok", latency_ms=0, details=None):
    """Send a heartbeat after startup or from a lightweight scheduler."""
    return requests.post(
        f"{METEORBASE_URL}/api/v1/apps/{os.environ.get('METEORBASE_SERVICE_NAME', '')}/heartbeat",
        headers={"X-Service-Secret": SERVICE_SECRET},
        json={"status": status, "latency_ms": latency_ms, "details": details or {}},
        timeout=8,
    )
