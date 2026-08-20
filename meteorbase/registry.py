from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify

from .db import get_supabase
from .security import require_user

bp = Blueprint("registry", __name__, url_prefix="/api/v1")

SAFE_SERVICE_COLS = "id, name, display_name, description, is_active, owner_user_id, last_seen_at, created_at, updated_at"
PUBLIC_SERVICE_COLS = "id, name, display_name, description, is_active, last_seen_at, created_at"


def _db_or_error():
    try:
        return get_supabase(), None
    except Exception:
        current_app.logger.exception("MeteorBase registry database connection failed")
        return None, (jsonify({"error": "Registry database is unavailable"}), 503)


def _normalize_name(name: str) -> str:
    return name.strip().lower()


@bp.get("/apps")
def list_apps():
    db, error = _db_or_error()
    if error:
        return error
    try:
        result = db.table("services").select(PUBLIC_SERVICE_COLS).eq("is_active", True).order("name").execute()
        rows = result.data
        if not isinstance(rows, list):
            raise RuntimeError("Registry query returned an invalid response")
        return jsonify({"apps": rows, "count": len(rows)})
    except Exception:
        current_app.logger.exception("Could not list services")
        return jsonify({"error": "Registry schema or database is unavailable"}), 503


@bp.get("/apps/<name>")
def get_app(name: str):
    db, error = _db_or_error()
    if error:
        return error
    try:
        result = db.table("services").select(PUBLIC_SERVICE_COLS).eq("name", _normalize_name(name)).eq("is_active", True).maybe_single().execute()
        if not result.data:
            return jsonify({"error": f"Service '{name}' not found"}), 404
        return jsonify({"app": result.data})
    except Exception:
        current_app.logger.exception("Could not read service")
        return jsonify({"error": "Registry schema or database is unavailable"}), 503


@bp.get("/apps/<name>/endpoints")
def list_endpoints(name: str):
    db, error = _db_or_error()
    if error:
        return error
    try:
        service = db.table("services").select("id").eq("name", _normalize_name(name)).eq("is_active", True).maybe_single().execute()
        if not service.data:
            return jsonify({"error": f"Service '{name}' not found"}), 404
        result = (
            db.table("service_endpoints")
            .select("id, method, path, description, requires_auth")
            .eq("service_id", service.data["id"])
            .order("method")
            .order("path")
            .execute()
        )
        return jsonify({"endpoints": result.data or []})
    except Exception:
        current_app.logger.exception("Could not list service endpoints")
        return jsonify({"error": "Registry schema or database is unavailable"}), 503


@bp.get("/me")
@require_user
def me():
    try:
        result = get_supabase().table("profiles").select("id, email, role, created_at, updated_at").eq("id", g.user_id).maybe_single().execute()
    except Exception:
        current_app.logger.exception("Could not read profile")
        return jsonify({"error": "Identity store is unavailable"}), 503
    if not result.data:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({"user": result.data})
