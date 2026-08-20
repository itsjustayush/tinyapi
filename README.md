# MeteorBase

**One API. Every app you ship.**

MeteorBase is a small, secure API hub for an ecosystem of independent microservices. A client uses one `X-API-Key` to call any registered service. MeteorBase validates the key, checks the service scope and endpoint allowlist, forwards the request with trusted server-to-server headers, logs the result, and returns the service response.

The production base URL is `https://tinyapi-urjr.onrender.com`.

## Architecture

```text
client app / script
        |
        | X-API-Key: mb_live_...
        v
https://tinyapi-urjr.onrender.com/api/v1/<service>/<path>
        |
        | validate key + scope + endpoint + active service
        | add X-Internal-Secret + X-Service-Secret + X-User-ID
        v
registered microservice receiver
        |
        | verify trusted headers, run normal app route
        v
service response -> MeteorBase -> client
```

MeteorBase owns the **control plane** rather than your product data. Each microservice keeps its own database and business logic. The gateway stores only routing metadata, authentication metadata, request telemetry, and service heartbeat data.

## What was rebuilt

The repository now contains a hardened Flask gateway with Supabase Auth integration, Google OAuth through the Supabase project, server-side JWT validation, hashed client API keys, service scopes, service-secret rotation, endpoint allowlisting, SSRF guardrails, request logging, heartbeats, Render health checks, a new futuristic landing page, an authenticated console, and end-to-end integration documentation.

New client keys are generated as `mb_live_...` values. Only a SHA-256 digest is stored in Supabase, and the raw secret is returned once. Existing deployments that still have a raw `api_key` column can run `supabase/migration_secure_keys.sql` before applying `supabase/schema.sql`.

## Setup

Run `supabase/schema.sql` in the Supabase SQL editor. Enable Google under **Authentication → Providers → Google**, and add `https://tinyapi-urjr.onrender.com/auth/callback` to the Supabase redirect allowlist. After the first account signs in, promote your admin profile:

```sql
update public.profiles
set role = 'admin'
where email = 'you@example.com';
```

Configure the variables from `.env.example`. The gateway requires `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, and a long random `INTERNAL_SECRET`. The service-role key must stay server-side and must never be inserted into a template.

Run locally with:

```bash
pip install -r requirements.txt
cp .env.example .env
python app.py
```

For Render, use `pip install -r requirements.txt` as the build command and:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 30 app:app
```

The included `render.yaml` uses `/healthz` for liveness. `/readyz` additionally verifies configuration and the required Supabase tables.

## How you link a microservice as admin

First, create the receiver route in the child app. Copy `examples/meteorbase_receiver.py` into that app, set `INTERNAL_SECRET` to the same random value used by MeteorBase, and set `METEORBASE_SERVICE_SECRET` to the secret returned by the registration response. The receiver should decorate its normal routes with `@require_meteorbase`.

Next, sign in at `/auth`, open `/dashboard`, and register the service in the **Services** panel. Enter a lowercase slug such as `oblivion` and a public receiver URL such as `https://oblivion.onrender.com/meteorbase`. The create response returns `service_secret` once. Save it in the child app's secret manager. Do not put it in frontend code.

Then, add endpoint rows. The gateway accepts a service in bootstrap mode when it has no endpoint rows. For production, add explicit `GET /sessions`, `POST /sessions`, or other routes so unknown paths are rejected before forwarding. You can create endpoint metadata through the admin console or `POST /api/v1/admin/services/<service_id>/endpoints`.

Finally, create a client API key in the **API keys** panel. Store it as `MB_API_KEY` in the client server or script. The client calls `https://tinyapi-urjr.onrender.com/api/v1/oblivion/sessions`; it never needs to know the child service URL or service secret.

A microservice can report its health with:

```bash
curl -X POST https://tinyapi-urjr.onrender.com/api/v1/apps/oblivion/heartbeat \
  -H "X-Service-Secret: $METEORBASE_SERVICE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"status":"ok","latency_ms":38}'
```

## API surface

| Method | Route | Authentication | Purpose |
|---|---|---|---|
| GET | `/healthz` | Public | Render liveness |
| GET | `/readyz` | Public | Configuration and schema readiness |
| GET | `/api/v1/apps` | Public | List active service metadata |
| GET | `/api/v1/apps/:name` | Public | Read one active service |
| GET | `/api/v1/apps/:name/endpoints` | Public | Read its endpoint catalog |
| GET | `/api/v1/me` | Supabase bearer JWT | Read the signed-in profile |
| GET | `/api/v1/keys` | Supabase bearer JWT | List the current user's key metadata |
| POST | `/api/v1/keys` | Supabase bearer JWT | Create a hashed API key; raw secret shown once |
| DELETE | `/api/v1/keys/:id` | Supabase bearer JWT | Revoke a key |
| PUT | `/api/v1/keys/:id/scopes` | Supabase bearer JWT | Replace service scopes |
| ANY | `/api/v1/:service/:path` | `X-API-Key` | Proxy a request to a registered service |
| POST | `/api/v1/apps/:name/heartbeat` | `X-Service-Secret` | Update service uptime |
| GET/POST/PATCH/DELETE | `/api/v1/admin/services...` | Admin bearer JWT | Manage services |
| GET/POST/DELETE | `/api/v1/admin/services/:id/endpoints...` | Admin bearer JWT | Manage endpoint allowlists |
| GET | `/api/v1/admin/logs` | Admin bearer JWT | Read gateway traffic |
| GET | `/api/v1/admin/heartbeats` | Admin bearer JWT | Read uptime telemetry |

## Client example

```python
from examples.meteorbase_client import MeteorBase

mb = MeteorBase(api_key="mb_live_...")
response = mb.get("oblivion", "/sessions")
response.raise_for_status()
print(response.json())
```

## Security model

Browser identity is handled by Supabase Auth and Google OAuth. Admin routes accept a Supabase access token, validate its signature using `SUPABASE_JWT_SECRET`, and confirm `profiles.role = 'admin'` from the service-role client.

Machine identity is separate. Clients use hashed, revocable, optionally expiring API keys. Service scopes are enforced by `api_key_service_access`; an empty scope set means all active services. The gateway never forwards the client's API key to a child app. Child apps receive only the private internal secret, their own service secret, the service slug, a generated request ID, and the forwarded user ID.

The proxy rejects unsafe schemes and private or loopback target hosts, disables redirects, strips hop-by-hop response headers, caps request size, applies a per-key in-memory rate limit, and writes request telemetry to Supabase. For a multi-instance deployment, replace the in-memory limiter with a shared Redis or database-backed limiter.

## Repository layout

```text
app.py                              Flask entrypoint and health routes
meteorbase/security.py              JWT, API-key hashing, rate limiting
meteorbase/client.py                user key and scope management
meteorbase/admin.py                 service registry and admin telemetry
meteorbase/proxy.py                 secure service proxy and heartbeats
meteorbase/registry.py               public catalog and current profile
supabase/schema.sql                  current database schema and RLS
supabase/migration_secure_keys.sql  raw-key migration for existing installs
examples/meteorbase_receiver.py     receiver guard for child services
examples/meteorbase_client.py        consumer SDK wrapper
docs/INTEGRATION_GUIDE.md            longer integration notes
templates/index.html                 futuristic landing page
templates/auth.html                  Supabase Auth and Google sign-in
templates/dashboard.html             client/admin console
templates/docs.html                  browser documentation
```
