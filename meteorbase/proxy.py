from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timezone
from hmac import compare_digest
from ipaddress import ip_address
from urllib.parse import urlparse
from uuid import uuid4

import requests
from flask import Blueprint, Response, current_app, g, jsonify, request

from .db import get_supabase
from .security import require_api_key

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
PROXY_TIMEOUT = max(1, int(os.environ.get("PROXY_TIMEOUT_SECONDS", "15")))
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length", "content-encoding"}
PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

bp = Blueprint("gateway", __name__, url_prefix="/api/v1")


def _normalize_path(path: str) -> str:
    cleaned = "/" + str(path or "").strip().strip("/")
    return cleaned if cleaned == "/" else cleaned.rstrip("/")


def _safe_service_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "127.0.0.1", "::1", "metadata.google.internal", "host.docker.internal"} or host.endswith(".local"):
            return False
        try:
            address = ip_address(host)
            addresses = [address]
        except ValueError:
            try:
                resolved = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
                addresses = [ip_address(item[4][0]) for item in resolved]
            except (OSError, ValueError):
                return False
        return bool(addresses) and all(not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified) for address in addresses)
    except Exception:
        return False


def _resolve_service(name: str):
    result = get_supabase().table("services").select("id, name, webhook_url, webhook_secret, is_active").eq("name", name.strip().lower()).maybe_single().execute()
    return result.data


def _service_access(api_key_id: str, service_id: str) -> bool:
    rows = get_supabase().table("api_key_service_access").select("service_id").eq("api_key_id", api_key_id).execute().data or []
    return not rows or any(item.get("service_id") == service_id for item in rows)


def _endpoint_allowed(service_id: str, method: str, path: str) -> bool:
    rows = get_supabase().table("service_endpoints").select("method, path").eq("service_id", service_id).execute().data or []
    if not rows:
        return True
    return any(item.get("method", "").upper() == method.upper() and _normalize_path(item.get("path", "")) == _normalize_path(path) for item in rows)


def _log_request(status: int, latency_ms: int, service: dict | None):
    try:
        get_supabase().table("request_logs").insert({
            "user_id": getattr(g, "user_id", None),
            "api_key_id": getattr(g, "api_key_id", None),
            "service_id": service.get("id") if service else None,
            "service_name": service.get("name") if service else None,
            "method": request.method,
            "path": request.full_path.rstrip("?"),
            "status_code": status,
            "latency_ms": int(latency_ms),
            "remote_ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        }).execute()
    except Exception:
        current_app.logger.warning("Unable to persist gateway request log", exc_info=True)


@bp.route("/<app_name>", defaults={"endpoint": ""}, methods=PROXY_METHODS)
@bp.route("/<app_name>/<path:endpoint>", methods=PROXY_METHODS)
@require_api_key
def route(app_name: str, endpoint: str):
    started = time.perf_counter()
    status = 500
    service = None
    request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
    try:
        service = _resolve_service(app_name)
        if not service:
            status = 404
            return jsonify({"error": f"Service '{app_name}' is not registered"}), status
        if not service.get("is_active"):
            status = 403
            return jsonify({"error": f"Service '{app_name}' is disabled"}), status
        if not _service_access(g.api_key_id, service["id"]):
            status = 403
            return jsonify({"error": f"API key has no access to '{app_name}'"}), status
        if not _endpoint_allowed(service["id"], request.method, f"/{endpoint}" if endpoint else "/"):
            status = 403
            return jsonify({"error": "Endpoint is not registered for this service"}), status
        if not INTERNAL_SECRET:
            status = 503
            return jsonify({"error": "Gateway forwarding is not configured"}), status
        if not service.get("webhook_secret") or not _safe_service_url(service.get("webhook_url", "")):
            status = 502
            return jsonify({"error": "Registered service URL is not permitted"}), status

        target = f"{service['webhook_url'].rstrip('/')}/{endpoint.lstrip('/')}" if endpoint else service["webhook_url"]
        forward_headers = {
            "Accept": request.headers.get("Accept", "application/json"),
            "X-Internal-Secret": INTERNAL_SECRET,
            "X-Service-Secret": service["webhook_secret"],
            "X-User-ID": str(g.user_id),
            "X-Service-Name": service["name"],
            "X-MeteorBase-Request-ID": request_id,
        }
        if request.headers.get("Content-Type"):
            forward_headers["Content-Type"] = request.headers["Content-Type"]
        if request.headers.get("User-Agent"):
            forward_headers["X-MeteorBase-Client"] = request.headers["User-Agent"][:240]

        upstream = requests.request(
            method=request.method,
            url=target,
            params=request.args,
            headers=forward_headers,
            data=request.get_data(cache=False),
            timeout=(5, PROXY_TIMEOUT),
            allow_redirects=False,
        )
        status = upstream.status_code
        response_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in HOP_BY_HOP}
        response_headers["X-MeteorBase-Request-ID"] = request_id
        return Response(upstream.content, status=status, headers=response_headers)
    except requests.RequestException:
        current_app.logger.warning("Gateway could not reach service %s", app_name, exc_info=True)
        status = 502
        return jsonify({"error": f"Failed to reach service '{app_name}'", "request_id": request_id}), status
    except Exception:
        current_app.logger.exception("Gateway routing exception for service %s", app_name)
        status = 500
        return jsonify({"error": "Gateway routing exception", "request_id": request_id}), status
    finally:
        _log_request(status, round((time.perf_counter() - started) * 1000), service)


@bp.post("/apps/<app_name>/heartbeat")
def heartbeat(app_name: str):
    provided = request.headers.get("X-Service-Secret", "")
    if not provided:
        return jsonify({"error": "Missing X-Service-Secret"}), 401
    try:
        db = get_supabase()
        result = db.table("services").select("id, name, webhook_secret, is_active").eq("name", app_name.strip().lower()).maybe_single().execute()
        service = result.data
        if not service or not service.get("is_active") or not compare_digest(provided, service.get("webhook_secret", "")):
            return jsonify({"error": "Unauthorized heartbeat"}), 403
        body = request.get_json(silent=True) or {}
        try:
            latency_ms = max(0, min(int(body.get("latency_ms", 0)), 60000))
        except (TypeError, ValueError):
            latency_ms = 0
        timestamp = datetime.now(timezone.utc).isoformat()
        db.table("service_heartbeats").insert({
            "service_id": service["id"],
            "status": str(body.get("status", "ok"))[:40],
            "latency_ms": latency_ms,
            "details": body.get("details") if isinstance(body.get("details"), dict) else None,
        }).execute()
        db.table("services").update({"last_seen_at": timestamp}).eq("id", service["id"]).execute()
        return jsonify({"ok": True, "service": service["name"], "ts": timestamp}), 200
    except Exception:
        current_app.logger.exception("Heartbeat processing failed")
        return jsonify({"error": "Heartbeat service unavailable"}), 503
