from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from .db import get_supabase
from .security import API_KEY_PREFIX, api_key_prefix, hash_api_key, require_user

bp = Blueprint("client", __name__, url_prefix="/api/v1")


def _valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _key_response(row: dict, scopes: list[str] | None = None) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "key_prefix": row.get("key_prefix"),
        "is_active": row.get("is_active"),
        "expires_at": row.get("expires_at"),
        "last_used_at": row.get("last_used_at"),
        "created_at": row.get("created_at"),
        "scopes": scopes if scopes is not None else [],
    }


@bp.get("/keys")
@require_user
def list_keys():
    try:
        db = get_supabase()
        keys = db.table("api_keys").select("id, name, key_prefix, is_active, expires_at, last_used_at, created_at").eq("user_id", g.user_id).order("created_at", desc=True).execute().data or []
        output = []
        for key in keys:
            scopes = db.table("api_key_service_access").select("service_id").eq("api_key_id", key["id"]).execute().data or []
            output.append(_key_response(key, [item["service_id"] for item in scopes]))
        return jsonify({"keys": output})
    except Exception:
        current_app.logger.exception("Could not list API keys")
        return jsonify({"error": "Could not load API keys"}), 503


@bp.post("/keys")
@require_user
def create_key():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "default").strip()[:80]
    if not name:
        return jsonify({"error": "Key name is required"}), 400

    expires_at = body.get("expires_at")
    if expires_at:
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed <= datetime.now(timezone.utc):
                return jsonify({"error": "expires_at must be in the future"}), 400
            expires_at = parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return jsonify({"error": "expires_at must be an ISO-8601 timestamp"}), 400

    raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    record = {
        "user_id": g.user_id,
        "name": name,
        "key_hash": hash_api_key(raw_key),
        "key_prefix": api_key_prefix(raw_key),
        "is_active": True,
        "expires_at": expires_at,
    }
    try:
        db = get_supabase()
        created = db.table("api_keys").insert(record).execute().data
        if not created:
            return jsonify({"error": "Could not create API key"}), 500
        row = created[0]
        scope_ids = body.get("service_ids") or []
        if not isinstance(scope_ids, list) or any(not _valid_uuid(item) for item in scope_ids):
            db.table("api_keys").delete().eq("id", row["id"]).eq("user_id", g.user_id).execute()
            return jsonify({"error": "service_ids must be a list of UUIDs"}), 400
        if scope_ids:
            db.table("api_key_service_access").insert([{"api_key_id": row["id"], "service_id": service_id} for service_id in sorted(set(scope_ids))]).execute()
        return jsonify({"key": raw_key, "warning": "Copy this secret now. It will never be shown again.", "metadata": _key_response(row, sorted(set(scope_ids)))}), 201
    except Exception:
        current_app.logger.exception("Could not create API key")
        return jsonify({"error": "Could not create API key"}), 503


@bp.delete("/keys/<key_id>")
@require_user
def revoke_key(key_id: str):
    if not _valid_uuid(key_id):
        return jsonify({"error": "Invalid key id"}), 400
    try:
        result = get_supabase().table("api_keys").update({"is_active": False}).eq("id", key_id).eq("user_id", g.user_id).execute()
        if not result.data:
            return jsonify({"error": "API key not found"}), 404
        return jsonify({"revoked": True, "id": key_id})
    except Exception:
        current_app.logger.exception("Could not revoke API key")
        return jsonify({"error": "Could not revoke API key"}), 503


@bp.put("/keys/<key_id>/scopes")
@require_user
def replace_scopes(key_id: str):
    if not _valid_uuid(key_id):
        return jsonify({"error": "Invalid key id"}), 400
    service_ids = (request.get_json(silent=True) or {}).get("service_ids", [])
    if not isinstance(service_ids, list) or any(not _valid_uuid(item) for item in service_ids):
        return jsonify({"error": "service_ids must be a list of UUIDs"}), 400
    try:
        db = get_supabase()
        key = db.table("api_keys").select("id").eq("id", key_id).eq("user_id", g.user_id).maybe_single().execute().data
        if not key:
            return jsonify({"error": "API key not found"}), 404
        db.table("api_key_service_access").delete().eq("api_key_id", key_id).execute()
        clean_ids = sorted(set(service_ids))
        if clean_ids:
            db.table("api_key_service_access").insert([{"api_key_id": key_id, "service_id": service_id} for service_id in clean_ids]).execute()
        return jsonify({"id": key_id, "service_ids": clean_ids})
    except Exception:
        current_app.logger.exception("Could not replace API key scopes")
        return jsonify({"error": "Could not update API key scopes"}), 503
