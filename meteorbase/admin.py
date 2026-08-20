from __future__ import annotations

import re
import secrets
from urllib.parse import urlparse
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from .db import get_supabase
from .security import require_admin

bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")
SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
SERVICE_COLS = "id, name, display_name, description, webhook_url, is_active, owner_user_id, last_seen_at, created_at, updated_at"


def _uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _service_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except Exception:
        return False


def _normalize_endpoint(raw: dict) -> dict:
    method = str(raw.get("method", "GET")).upper().strip()
    path = str(raw.get("path", "/")).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        raise ValueError("method must be GET, POST, PUT, PATCH, DELETE, HEAD, or OPTIONS")
    if len(path) > 240 or ".." in path:
        raise ValueError("path must be a safe absolute route")
    return {
        "method": method,
        "path": path,
        "description": str(raw.get("description") or "").strip()[:240] or None,
        "requires_auth": bool(raw.get("requires_auth", True)),
    }


@bp.get("/services")
@require_admin
def list_services():
    try:
        result = get_supabase().table("services").select(SERVICE_COLS).order("name").execute()
        return jsonify({"services": result.data or []})
    except Exception:
        current_app.logger.exception("Could not list services")
        return jsonify({"error": "Could not load services"}), 503


@bp.post("/services")
@require_admin
def create_service():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip().lower()
    display_name = str(body.get("display_name") or name).strip()[:100]
    description = str(body.get("description") or "").strip()[:500] or None
    webhook_url = str(body.get("webhook_url") or "").strip().rstrip("/")
    if not SERVICE_NAME_RE.fullmatch(name):
        return _json_error("name must be a lowercase slug with 3–50 characters")
    if not _service_url(webhook_url):
        return _json_error("webhook_url must be an absolute http(s) URL")

    webhook_secret = f"ms_{secrets.token_urlsafe(32)}"
    record = {
        "name": name,
        "display_name": display_name or name,
        "description": description,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "is_active": bool(body.get("is_active", True)),
        "owner_user_id": body.get("owner_user_id") if _uuid(str(body.get("owner_user_id"))) else None,
    }
    try:
        db = get_supabase()
        created = db.table("services").insert(record).execute().data
        if not created:
            return _json_error("Could not create service", 500)
        service = created[0]
        endpoints = body.get("endpoints") or []
        if not isinstance(endpoints, list):
            return _json_error("endpoints must be a list")
        normalized = [{"service_id": service["id"], **_normalize_endpoint(endpoint)} for endpoint in endpoints]
        if normalized:
            db.table("service_endpoints").insert(normalized).execute()
        public = {key: service.get(key) for key in SERVICE_COLS.split(", ")}
        return jsonify({"service": public, "service_secret": webhook_secret, "warning": "Store this service secret in the receiver app. It will not be shown again."}), 201
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception:
        current_app.logger.exception("Could not create service")
        return _json_error("Could not create service", 503)


@bp.patch("/services/<service_id>")
@require_admin
def update_service(service_id: str):
    if not _uuid(service_id):
        return _json_error("Invalid service id")
    body = request.get_json(silent=True) or {}
    updates: dict = {}
    for field in ("display_name", "description"):
        if field in body:
            updates[field] = str(body[field] or "").strip()[:500] or None
    if "webhook_url" in body:
        webhook_url = str(body["webhook_url"]).strip().rstrip("/")
        if not _service_url(webhook_url):
            return _json_error("webhook_url must be an absolute http(s) URL")
        updates["webhook_url"] = webhook_url
    if "is_active" in body:
        updates["is_active"] = bool(body["is_active"])
    if not updates:
        return _json_error("No editable fields supplied")
    try:
        result = get_supabase().table("services").update(updates).eq("id", service_id).execute()
        if not result.data:
            return _json_error("Service not found", 404)
        return jsonify({"service": result.data[0]})
    except Exception:
        current_app.logger.exception("Could not update service")
        return _json_error("Could not update service", 503)


@bp.delete("/services/<service_id>")
@require_admin
def delete_service(service_id: str):
    if not _uuid(service_id):
        return _json_error("Invalid service id")
    try:
        result = get_supabase().table("services").delete().eq("id", service_id).execute()
        if not result.data:
            return _json_error("Service not found", 404)
        return jsonify({"deleted": True, "id": service_id})
    except Exception:
        current_app.logger.exception("Could not delete service")
        return _json_error("Could not delete service", 503)


@bp.post("/services/<service_id>/rotate-secret")
@require_admin
def rotate_secret(service_id: str):
    if not _uuid(service_id):
        return _json_error("Invalid service id")
    secret = f"ms_{secrets.token_urlsafe(32)}"
    try:
        result = get_supabase().table("services").update({"webhook_secret": secret}).eq("id", service_id).execute()
        if not result.data:
            return _json_error("Service not found", 404)
        return jsonify({"service_secret": secret, "warning": "Update the receiver before restarting traffic."})
    except Exception:
        current_app.logger.exception("Could not rotate service secret")
        return _json_error("Could not rotate service secret", 503)


@bp.get("/services/<service_id>/endpoints")
@require_admin
def list_service_endpoints(service_id: str):
    if not _uuid(service_id):
        return _json_error("Invalid service id")
    try:
        result = get_supabase().table("service_endpoints").select("id, service_id, method, path, description, requires_auth, created_at").eq("service_id", service_id).order("path").execute()
        return jsonify({"endpoints": result.data or []})
    except Exception:
        current_app.logger.exception("Could not list endpoints")
        return _json_error("Could not load endpoints", 503)


@bp.post("/services/<service_id>/endpoints")
@require_admin
def create_service_endpoints(service_id: str):
    if not _uuid(service_id):
        return _json_error("Invalid service id")
    body = request.get_json(silent=True) or {}
    raw_items = body if isinstance(body, list) else body.get("endpoints", [body])
    if not isinstance(raw_items, list) or not raw_items:
        return _json_error("Provide one endpoint object or an endpoints list")
    try:
        records = [{"service_id": service_id, **_normalize_endpoint(item)} for item in raw_items]
        result = get_supabase().table("service_endpoints").insert(records).execute()
        return jsonify({"endpoints": result.data or []}), 201
    except ValueError as exc:
        return _json_error(str(exc))
    except Exception:
        current_app.logger.exception("Could not create endpoints")
        return _json_error("Could not create endpoints", 503)


@bp.delete("/services/<service_id>/endpoints/<endpoint_id>")
@require_admin
def delete_service_endpoint(service_id: str, endpoint_id: str):
    if not _uuid(service_id) or not _uuid(endpoint_id):
        return _json_error("Invalid service or endpoint id")
    try:
        result = get_supabase().table("service_endpoints").delete().eq("id", endpoint_id).eq("service_id", service_id).execute()
        if not result.data:
            return _json_error("Endpoint not found", 404)
        return jsonify({"deleted": True, "id": endpoint_id})
    except Exception:
        current_app.logger.exception("Could not delete endpoint")
        return _json_error("Could not delete endpoint", 503)


@bp.get("/logs")
@require_admin
def logs():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    try:
        result = get_supabase().table("request_logs").select("id, user_id, api_key_id, service_id, service_name, method, path, status_code, latency_ms, remote_ip, created_at").order("created_at", desc=True).limit(limit).execute()
        return jsonify({"logs": result.data or []})
    except Exception:
        current_app.logger.exception("Could not read request logs")
        return _json_error("Could not load request logs", 503)


@bp.get("/heartbeats")
@require_admin
def heartbeats():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    try:
        result = get_supabase().table("service_heartbeats").select("id, service_id, status, latency_ms, details, created_at").order("created_at", desc=True).limit(limit).execute()
        return jsonify({"heartbeats": result.data or []})
    except Exception:
        current_app.logger.exception("Could not read service heartbeats")
        return _json_error("Could not load heartbeats", 503)
