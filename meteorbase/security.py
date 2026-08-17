"""Security decorators and helpers for the MeteorBase gateway."""
import os
import time
from datetime import datetime, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from .db import get_supabase

JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))

# Simple in-memory fixed-window rate limiter (single instance).
_window_start = time.time()
_window_counts: dict[str, int] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _rate_limit(scope: str) -> bool:
    """True if the scope is allowed, False if throttled."""
    global _window_start, _window_counts
    now = time.time()
    if now - _window_start >= 60:
        _window_start = now
        _window_counts = {}
    count = _window_counts.get(scope, 0)
    if count >= RATE_LIMIT_PER_MINUTE:
        return False
    _window_counts[scope] = count + 1
    return True


def require_api_key(f):
    """Validate the X-API-Key header and inject g.user_id / g.api_key_id."""

    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401

        if not _rate_limit(api_key):
            return jsonify({"error": "Rate limit exceeded. Try again shortly."}), 429

        db = get_supabase()
        res = (
            db.table("api_keys")
            .select("id, user_id, is_active, expires_at")
            .eq("api_key", api_key)
            .maybe_single()
            .execute()
        )
        row = res.data
        if not row:
            return jsonify({"error": "Invalid API key"}), 401
        if not row.get("is_active"):
            return jsonify({"error": "API key is revoked"}), 403

        expires = row.get("expires_at")
        if expires:
            exp = _parse_iso(expires)
            if exp and exp < datetime.now(timezone.utc):
                return jsonify({"error": "API key expired"}), 403

        g.user_id = row["user_id"]
        g.api_key_id = row["id"]
        db.table("api_keys").update({"last_used_at": _now_iso()}).eq(
            "id", row["id"]
        ).execute()
        return f(*args, **kwargs)

    return decorated


def _extract_bearer() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def require_admin(f):
    """Validate a browser JWT and require the profile role to be 'admin'."""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer()
        if not token:
            return jsonify({"error": "Missing bearer token"}), 401
        if not JWT_SECRET:
            return jsonify({"error": "Server not configured for JWT validation"}), 500
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify({"error": "Invalid or expired token"}), 401

        db = get_supabase()
        res = (
            db.table("profiles")
            .select("role")
            .eq("id", payload.get("sub"))
            .maybe_single()
            .execute()
        )
        if not res.data or res.data.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403

        g.user_id = payload.get("sub")
        g.is_admin = True
        return f(*args, **kwargs)

    return decorated