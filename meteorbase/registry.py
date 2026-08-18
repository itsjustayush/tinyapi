"""Public metadata endpoints: what apps exist, their endpoints, and /me.

These are intentionally read-only and never expose internal secrets
(the gateway server is the only thing that reads webhook_secret).
"""
import os

import jwt
from flask import Blueprint, current_app, jsonify, request

from .db import get_supabase

JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

# Safe public columns - NEVER include webhook_secret here.
SAFE_COLS = (
    "id, name, display_name, description, is_active, "
    "last_seen_at, created_at, updated_at"
)

bp = Blueprint("registry", __name__, url_prefix="/api/v1")


def _db():
    try:
        return get_supabase(), None
    except Exception:
        current_app.logger.exception("MeteorBase registry database connection failed")
        return None, "Registry database is unavailable"


@bp.route("/apps", methods=["GET"])
def list_apps():
    db, err = _db()
    if db is None:
        return jsonify({"error": err}), 503
    res = db.table("services").select(SAFE_COLS).order("name").execute()
    return jsonify({"apps": res.data})


@bp.route("/apps/<name>", methods=["GET"])
def get_app(name: str):
    db, err = _db()
    if db is None:
        return jsonify({"error": err}), 503
    res = (
        db.table("services")
        .select(SAFE_COLS)
        .eq("name", name.lower())
        .maybe_single()
        .execute()
    )
    if not res.data:
        return jsonify({"error": f"App '{name}' not found"}), 404
    return jsonify({"app": res.data})


@bp.route("/apps/<name>/endpoints", methods=["GET"])
def list_endpoints(name: str):
    db, err = _db()
    if db is None:
        return jsonify({"error": err}), 503
    svc = (
        db.table("services")
        .select("id")
        .eq("name", name.lower())
        .maybe_single()
        .execute()
    )
    if not svc.data:
        return jsonify({"error": f"App '{name}' not found"}), 404
    res = (
        db.table("service_endpoints")
        .select("id, method, path, description, requires_auth")
        .eq("service_id", svc.data["id"])
        .order("method")
        .execute()
    )
    return jsonify({"endpoints": res.data})


@bp.route("/me", methods=["GET"])
def me():
    """Return the profile of the logged-in user (drives the dashboard role)."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        return jsonify({"error": "Missing bearer token"}), 401
    if not JWT_SECRET:
        return jsonify({"error": "Server not configured for JWT validation"}), 500
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return jsonify({"error": "Invalid or expired token"}), 401

    db, err = _db()
    if db is None:
        return jsonify({"error": err}), 503
    res = (
        db.table("profiles")
        .select("id, email, role")
        .eq("id", payload.get("sub"))
        .maybe_single()
        .execute()
    )
    if not res.data:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({"user": res.data})
