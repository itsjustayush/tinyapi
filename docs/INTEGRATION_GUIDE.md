# MeteorBase integration guide

This guide describes the complete link between a client, MeteorBase, and one of your microservices. The public gateway base URL is `https://tinyapi-urjr.onrender.com`.

## The contract

A client calls:

```text
METHOD https://tinyapi-urjr.onrender.com/api/v1/<service-name>/<service-path>
X-API-Key: mb_live_...
```

MeteorBase resolves `<service-name>` in Supabase, checks the API-key hash, expiry, revocation state, service scope, and endpoint allowlist, then forwards the request to the registered `webhook_url`. The gateway adds:

```text
X-Internal-Secret: <shared gateway secret>
X-Service-Secret: <service-specific secret>
X-User-ID: <Supabase user id attached to the client key>
X-Service-Name: <service slug>
X-MeteorBase-Request-ID: <request id>
```

A receiver must verify the first two headers before executing its route. It can use `X-User-ID` to scope records in its own database.

## Admin registration

Sign in to `/auth` with Google or email, promote the first profile to `admin` in Supabase, and open `/dashboard`. In the Services panel, create a service with a lowercase slug and the URL of the receiver endpoint. The response returns `service_secret` exactly once.

The equivalent request is:

```bash
curl -X POST https://tinyapi-urjr.onrender.com/api/v1/admin/services \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "oblivion",
    "display_name": "Oblivion",
    "description": "Sessions and operational data",
    "webhook_url": "https://oblivion.onrender.com/meteorbase",
    "endpoints": [
      {"method":"GET","path":"/sessions","description":"List sessions"},
      {"method":"POST","path":"/sessions","description":"Create a session"}
    ]
  }'
```

Copy the returned secret into the service's environment as `METEORBASE_SERVICE_SECRET`. If the secret is exposed, rotate it from the admin console or call `POST /api/v1/admin/services/<service_id>/rotate-secret`, then update the receiver before traffic resumes.

## Receiver setup

Copy `examples/meteorbase_receiver.py` into the child app and set:

```bash
INTERNAL_SECRET=<same value as MeteorBase>
METEORBASE_SERVICE_SECRET=<secret returned at registration>
METEORBASE_SERVICE_NAME=oblivion
METEORBASE_URL=https://tinyapi-urjr.onrender.com
```

A Flask receiver can then look like this:

```python
from flask import Flask, jsonify, request
from meteorbase_receiver import require_meteorbase

app = Flask(__name__)

@app.get("/sessions")
@require_meteorbase
def sessions():
    return jsonify({
        "user_id": request.headers["X-User-ID"],
        "sessions": [],
    })
```

The child app's public route is not the client contract. Clients call MeteorBase, not the receiver URL. Keep the receiver URL and service secret in server-side configuration.

## Heartbeats

A service can report its status after startup and periodically thereafter:

```python
from meteorbase_receiver import ping_meteorbase

response = ping_meteorbase(status="ok", latency_ms=38)
response.raise_for_status()
```

The gateway authenticates the service secret, inserts a heartbeat, and updates `services.last_seen_at`.

## Client setup

Create a client key in the console. The raw key is displayed once and only its hash is stored. Put it in a server-side secret manager:

```bash
export MB_API_KEY='mb_live_...'
```

Then call any registered service:

```bash
curl https://tinyapi-urjr.onrender.com/api/v1/oblivion/sessions \
  -H "X-API-Key: $MB_API_KEY" \
  -H "Accept: application/json"
```

The Python wrapper in `examples/meteorbase_client.py` uses the same contract:

```python
from examples.meteorbase_client import MeteorBase

mb = MeteorBase()
response = mb.get("oblivion", "/sessions")
response.raise_for_status()
```

## Endpoint allowlists and scopes

If a service has no `service_endpoints` rows, the gateway runs in bootstrap mode for that service. Once one endpoint is registered, every routed method/path must match a row. This lets you bootstrap quickly but lock the service down before production.

A client key with no `api_key_service_access` rows can access every active service. To limit a key, replace its scopes through `PUT /api/v1/keys/<key_id>/scopes` with a JSON body such as `{"service_ids":["<service-uuid>"]}`.

## Troubleshooting

A `401` usually means the client key or bearer token is missing or invalid. A `403` means the key is revoked, expired, out of scope, or the endpoint is not allowlisted. A `502` means the registered receiver URL is unreachable or blocked by the gateway's target-host safety checks. A `503` from `/readyz` means Render is missing an environment variable or Supabase does not yet contain the current schema.
