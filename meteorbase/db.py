from __future__ import annotations

import os
from typing import Any

from supabase import Client, create_client

_client: Client | None = None

_REQUIRED_SCHEMA = {
    "profiles": "id, role",
    "services": "id, name, display_name, description, webhook_url, webhook_secret, is_active, owner_user_id, last_seen_at, created_at, updated_at",
    "service_endpoints": "id, service_id, method, path, description, requires_auth",
    "api_keys": "id, user_id, name, key_hash, key_prefix, is_active, expires_at, last_used_at, created_at",
    "api_key_service_access": "id, api_key_id, service_id",
    "request_logs": "id",
    "service_heartbeats": "id",
}


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


def reset_supabase_client() -> None:
    global _client
    _client = None


def verify_gateway_schema() -> None:
    db = get_supabase()
    for table, columns in _REQUIRED_SCHEMA.items():
        db.table(table).select(columns).limit(1).execute()


def first(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else None
