"""The core MeteorBase proxy: dynamic routing to registered child apps."""
import os
import time
from datetime import datetime, timezone

import requests
from flask import Blueprint, Response, g, jsonify, request

from .db import get_supabase
from .security import require_api_key

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "change-me-in-production")
PROXY_TIMEOUT = int(os.environ.get("PROXY_TIMEOUT_SECONDS", "15"))

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "content-encoding",
}

bp = Blueprint("gateway", __name__, url_prefix="/api/v1")


def _normalize(path: str) -> str:
    return path.strip("/")


def _resolve_service(app_name: str):
    db = get_supabase()
    res = (
        db.table("services")
        .select("id, name, webhook_url, webhook_secret, is_active")
        .eq("name", app_name.lower())
        .maybe_single()
        .execute()
    )
    return res.data


def _has_service_access(api_key_id: str, service_id: str) -> bool:
    """Empty scope set = unrestricted key (all services)."""
    db = get_supabase()
    res = (
        db.table("api_key_service_access")
        .select("service_id")
        .eq("api_key_id", api_key_id)
        .execute()
    )
    if not res.data:
        return True
    return any(r["service_id"] == service_id for r in res.data)


def _endpoint_allowed(service_id: str, method: str, path: str) -> bool:
    """Validate method + path against the app's registered metadata.

    If the app has not registered endpoints yet, the gateway runs in
    open mode so you can bootstrap quickly - register endpoints via the
    admin API to lock the app down.
    """
    db = get_supabase()
    res = (
        db.table("service_endpoints")
        .select("method, path")
        .eq("service_id", service_id)
        .execute()
    )
    if not res.data:
        return True
    return any(
        r["method"].upper() == method.upper()
        and _normalize(r["path"]) == _normalize(path)
        for r in res.data
    )


def _log(status: int, latency_ms: int, service: dict | None):
    try:
        db = get_supabase()
        db.table("request_logs").insert(
            {
                "user_id": getattr(g, "user_id", None),
                "api_key_id": getattr(g, "api_key_id", None),
                "service_id": service["id"] if service else None,
                "service_name": service["name"] if service else None,
                "method": request.method,
                "path": request.full_path.rstrip("?"),
                "status_code": status,
                "latency_ms": int(latency_ms),
                "remote_ip": request.remote_addr,
            }
        ).execute()
    except Exception:
        pass


@bp.route("/<app_name>/<path:endpoint>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@require_api_key
def route(app_name: str, endpoint: str):
    start = time.time()
    status = 500
    service = None
    try:
        service = _resolve_service(app_name)
        if not service:
            status = 404
            return jsonify({"error": f"Service '{app_name}' is not registered."}), 404
        if not service["is_active"]:
            status = 403
            return jsonify({"error": f"Service '{app_name}' is disabled."}), 403
        if not _has_service_access(g.api_key_id, service["id"]):
            status = 403
            return jsonify({"error": f"API key has no access to '{app_name}'."}), 403
        if not _endpoint_allowed(service["id"], request.method, endpoint):
            status = 403
            return jsonify(
                {"error": f"Endpoint {request.method} /{endpoint} is not registered on '{app_name}'."}
            ), 403

        target_url = f"{service['webhook_url'].rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": request.headers.get("Content-Type", "application/json"),
            "Accept": request.headers.get("Accept", "application/json"),
            "X-Internal-Secret": INTERNAL_SECRET,
            "X-Service-Secret": service["webhook_secret"],
            "X-User-ID": g.user_id,
            "X-Service-Name": service["name"],
        }

        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            timeout=PROXY_TIMEOUT,
        )
        status = resp.status_code
        out_headers = {
            k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP
        }
        return Response(resp.content, status=resp.status_code, headers=out_headers)

    except requests.exceptions.RequestException as e:
        status = 502
        return jsonify(
            {"error": f"Failed to reach service '{app_name}'.", "details": str(e)}
        ), 502
    except Exception as e:
        status = 500
        return jsonify(
            {"error": "Gateway routing exception.", "details": str(e)}
        ), 500
    finally:
        _log(status, (time.time() - start) * 1000, service)


# --- App-side heartbeat: each child app pings this for uptime ---
@bp.route("/apps/<app_name>/heartbeat", methods=["POST"])
def heartbeat(app_name: str):
    secret = request.headers.get("X-Service-Secret")
    try:
        db = get_supabase()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    res = (
        db.table("services")
        .select("id, webhook_secret, is_active")
        .eq("name", app_name.lower())
        .maybe_single()
        .execute()
    )
    svc = res.data
    if not svc or svc["webhook_secret"] != secret:
        return jsonify({"error": "Unauthorized heartbeat"}), 403

    body = request.get_json(silent=True) or {}
    now = datetime.now(timezone.utc).isoformat()
    db.table("service_heartbeats").insert(
        {
            "service_id": svc["id"],
            "status": body.get("status", "ok"),
            "latency_ms": int(body.get("latency_ms", 0)),
            "details": body.get("details"),
        }
    ).execute()
    db.table("services").update({"last_seen_at": now}).eq("id", svc["id"]).execute()
    return jsonify({"ok": True, "service": app_name, "ts": now}), 200