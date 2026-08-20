from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

import jwt
from flask import current_app, g, jsonify, request

from .db import get_supabase

API_KEY_PREFIX = os.environ.get("API_KEY_PREFIX", "mb_live_")
RATE_LIMIT_PER_MINUTE = max(1, int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120")))
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

_window_lock = threading.Lock()
_window_start = time.monotonic()
_window_counts: dict[str, int] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def canonical_api_key(value: str) -> str:
    """Return the token body for compatibility with older callers."""
    clean = value.strip()
    return clean[len(API_KEY_PREFIX):] if clean.startswith(API_KEY_PREFIX) else clean


def hash_api_key(value: str) -> str:
    return hashlib.sha256(canonical_api_key(value).encode("utf-8")).hexdigest()


def api_key_prefix(value: str) -> str:
    clean = value.strip()
    return clean[: len(API_KEY_PREFIX) + 8]


def _rate_limit(scope: str) -> bool:
    global _window_start, _window_counts
    now = time.monotonic()
    with _window_lock:
        if now - _window_start >= 60:
            _window_start = now
            _window_counts = {}
        current = _window_counts.get(scope, 0)
        if current >= RATE_LIMIT_PER_MINUTE:
            return False
        _window_counts[scope] = current + 1
        return True


def _auth_error(message: str, status: int = 401):
    return jsonify({"error": message}), status


def require_api_key(view: Callable[..., Any]):
    @wraps(view)
    def decorated(*args, **kwargs):
        presented = request.headers.get("X-API-Key", "").strip()
        if not presented or not presented.startswith(API_KEY_PREFIX):
            return _auth_error(f"Missing or malformed X-API-Key. Expected a key starting with {API_KEY_PREFIX}.")

        digest = hash_api_key(presented)
        if not _rate_limit(digest):
            return jsonify({"error": "Rate limit exceeded", "retry_after_seconds": 60}), 429

        try:
            db = get_supabase()
            result = (
                db.table("api_keys")
                .select("id, user_id, name, key_hash, is_active, expires_at")
                .eq("key_hash", digest)
                .maybe_single()
                .execute()
            )
        except Exception:
            current_app.logger.exception("API key lookup failed")
            return jsonify({"error": "Gateway identity store is unavailable"}), 503

        row = result.data
        if not row:
            return _auth_error("Invalid API key")
        if not row.get("is_active"):
            return _auth_error("API key is revoked", 403)

        expires_at = parse_iso(row.get("expires_at"))
        if expires_at and expires_at <= utc_now():
            return _auth_error("API key has expired", 403)

        g.user_id = row["user_id"]
        g.api_key_id = row["id"]
        g.api_key_name = row.get("name")
        g.api_key_prefix = presented[: len(API_KEY_PREFIX) + 8]

        try:
            db.table("api_keys").update({"last_used_at": now_iso()}).eq("id", row["id"]).execute()
        except Exception:
            current_app.logger.warning("Could not update API key last_used_at", exc_info=True)

        return view(*args, **kwargs)

    return decorated


def _extract_bearer() -> str | None:
    value = request.headers.get("Authorization", "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else None


def decode_user_jwt(token: str) -> dict[str, Any]:
    if not JWT_SECRET:
        raise RuntimeError("SUPABASE_JWT_SECRET is not configured")

    options = {"verify_aud": bool(os.environ.get("SUPABASE_JWT_AUDIENCE"))}
    kwargs: dict[str, Any] = {
        "algorithms": ["HS256"],
        "options": options,
    }
    if os.environ.get("SUPABASE_JWT_AUDIENCE"):
        kwargs["audience"] = os.environ["SUPABASE_JWT_AUDIENCE"]
    if os.environ.get("SUPABASE_JWT_ISSUER"):
        kwargs["issuer"] = os.environ["SUPABASE_JWT_ISSUER"]
    return jwt.decode(token, JWT_SECRET, **kwargs)


def require_user(view: Callable[..., Any]):
    @wraps(view)
    def decorated(*args, **kwargs):
        token = _extract_bearer()
        if not token:
            return _auth_error("Missing bearer token")
        try:
            payload = decode_user_jwt(token)
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
        except jwt.PyJWTError:
            return _auth_error("Invalid or expired token")

        user_id = payload.get("sub")
        if not user_id:
            return _auth_error("Token does not contain a subject")
        g.user_id = user_id
        g.jwt_claims = payload
        return view(*args, **kwargs)

    return decorated


def require_admin(view: Callable[..., Any]):
    @wraps(view)
    @require_user
    def decorated(*args, **kwargs):
        try:
            result = get_supabase().table("profiles").select("id, email, role").eq("id", g.user_id).maybe_single().execute()
        except Exception:
            current_app.logger.exception("Admin profile lookup failed")
            return jsonify({"error": "Identity store is unavailable"}), 503
        profile = result.data
        if not profile or profile.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        g.profile = profile
        g.is_admin = True
        return view(*args, **kwargs)

    return decorated
