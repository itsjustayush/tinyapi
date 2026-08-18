import os

from supabase import create_client, Client

_client: Client | None = None

_REQUIRED_SCHEMA = {
    "services": "id, name, display_name, description, webhook_url, webhook_secret, is_active, last_seen_at, created_at, updated_at",
    "service_endpoints": "id",
    "api_keys": "id",
    "api_key_service_access": "id",
    "request_logs": "id",
    "service_heartbeats": "id",
}


def get_supabase() -> Client:
    """Lazy singleton Supabase client.

    The gateway uses the service_role key so it can read internal
    secrets and write logs/heartbeats, bypassing RLS. The browser
    templates use the anon key via the SUPABASE_ANON_KEY env var.
    """
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = (
            os.environ.get("SUPABASE_SERVICE_KEY")
            or os.environ.get("SUPABASE_KEY")
        )
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
            )
        _client = create_client(url, key)
    return _client


def verify_gateway_schema() -> None:
    """Raise if a required MeteorBase table or services column is unavailable."""
    db = get_supabase()
    for table, columns in _REQUIRED_SCHEMA.items():
        db.table(table).select(columns).limit(1).execute()
