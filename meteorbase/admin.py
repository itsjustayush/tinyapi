"""Admin API: register / manage child apps and their endpoints.

Every endpoint here requires an admin JWT (validated server-side via
require_admin). Nothing is hardcoded - apps are created and updated
from real form data and stored in Supabase.
"""
from flask import Blueprint, g, jsonify, request

from .db import get_supabase
from .security import require_admin

bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@bp.route("/services", methods=["GET"])
@require_admin
def list_services():
    db = get_supabase()
    res = (
        db.table("services")
        .select("*, service_endpoints(id, method, path, description, requires_auth)")
        .order("name")
        .execute()
    )
    return jsonify({"services": res.data})


@bp.route("/services", methods=["POST"])
@require_admin
def create_service():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip().lower()
    webhook_url = (data.get("webhook_url") or "").strip().rstrip("/")
    if not name or not webhook_url:
        return jsonify({"error": "name and webhook_url are required"}), 400

    db = get_supabase()
    try:
        res = db.table("services").insert(
            {
                "name": name,
                "display_name": (data.get("display_name") or "").strip() or None,
                "description": (data.get("description") or "").strip() or None,
                "webhook_url": webhook_url,
                "owner_user_id": g.user_id,
            }
        ).execute()
        row = res.data[0]
        return jsonify({"ok": True, "service": row}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/services/<service_id>", methods=["PATCH"])
@require_admin
def update_service(service_id: str):
    data = request.get_json(silent=True) or {}
    db = get_supabase()
    allowed = {"name", "display_name", "description", "webhook_url", "is_active"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if "name" in updates:
        updates["name"] = updates["name"].strip().lower()
    if "webhook_url" in updates:
        updates["webhook_url"] = updates["webhook_url"].strip().rstrip("/")
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    try:
        res = (
            db.table("services")
            .update(updates)
            .eq("id", service_id)
            .execute()
        )
        if not res.data:
            return jsonify({"error": "Service not found"}), 404
        return jsonify({"ok": True, "service": res.data[0]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/services/<service_id>", methods=["DELETE"])
@require_admin
def delete_service(service_id: str):
    db = get_supabase()
    try:
        db.table("service_endpoints").delete().eq("service_id", service_id).execute()
        res = db.table("services").delete().eq("id", service_id).execute()
        if not res.data:
            return jsonify({"error": "Service not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/services/<service_id>/endpoints", methods=["GET"])
@require_admin
def list_service_endpoints(service_id: str):
    db = get_supabase()
    res = (
        db.table("service_endpoints")
        .select("id, method, path, description, requires_auth")
        .eq("service_id", service_id)
        .order("method")
        .execute()
    )
    return jsonify({"endpoints": res.data})


@bp.route("/services/<service_id>/endpoints", methods=["POST"])
@require_admin
def add_endpoints(service_id: str):
    data = request.get_json(silent=True) or {}
    items = data if isinstance(data, list) else [data]
    payload = []
    for it in items:
        method = (it.get("method") or "").upper()
        path = (it.get("path") or "").strip()
        if method not in _METHODS or not path:
            return jsonify({"error": "Each endpoint needs method and path"}), 400
        payload.append(
            {
                "service_id": service_id,
                "method": method,
                "path": path,
                "description": it.get("description"),
                "requires_auth": bool(it.get("requires_auth", True)),
            }
        )
    db = get_supabase()
    try:
        res = db.table("service_endpoints").insert(payload).execute()
        return jsonify({"ok": True, "endpoints": res.data}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/services/<service_id>/endpoints/<endpoint_id>", methods=["DELETE"])
@require_admin
def delete_endpoint(service_id: str, endpoint_id: str):
    db = get_supabase()
    try:
        res = (
            db.table("service_endpoints")
            .delete()
            .eq("id", endpoint_id)
            .eq("service_id", service_id)
            .execute()
        )
        if not res.data:
            return jsonify({"error": "Endpoint not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/logs", methods=["GET"])
@require_admin
def logs():
    db = get_supabase()
    limit = min(int(request.args.get("limit", 100)), 500)
    q = db.table("request_logs").select("*").order("created_at", desc=True).limit(limit)
    service_name = request.args.get("service")
    if service_name:
        q = q.eq("service_name", service_name.lower())
    res = q.execute()
    return jsonify({"logs": res.data})


@bp.route("/heartbeats", methods=["GET"])
@require_admin
def heartbeats():
    db = get_supabase()
    limit = min(int(request.args.get("limit", 50)), 200)
    q = (
        db.table("service_heartbeats")
        .select("*, services!inner(name)")
        .order("created_at", desc=True)
        .limit(limit)
    )
    service_name = request.args.get("service")
    if service_name:
        q = q.eq("services.name", service_name.lower())
    res = q.execute()
    return jsonify({"heartbeats": res.data})