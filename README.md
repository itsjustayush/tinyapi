# MeteorBase

**One API. Every app you've ever built — VEX, SkipIdeate, Oblivion, and every future project.**

MeteorBase is a **unified API gateway** that sits in front of all your apps. It is NOT an app
with its own data model — it is the **middleman**:

- Your apps keep their own logic, routes, and databases and simply expose a **webhook receiver**.
- Clients (your users, your other projects, your scripts) only ever talk to **MeteorBase**.
- MeteorBase validates the user, their API key, the app's validity, and the endpoint metadata,
  then forwards the request to the right app with trusted headers, logs the traffic, and returns
  the app's response.
- Apps ping MeteorBase for **uptime tracking**.

All registration data (app names, webhook URLs, endpoint metadata, keys) lives in **Supabase**
as real database rows — nothing is hardcoded.

## Architecture

```
CLIENT                              METEORBASE (gateway + Supabase)            YOUR APP (webhook)
─────────                           ─────────────────────────────────          ─────────────────
X-API-Key: mb_live_...   ───────▶   1. validate API key                        receiver endpoint
GET /api/v1/oblivion/sessions       2. look up app by name in `services`  ─▶   validates
                                    3. check key scope / app active           X-Internal-Secret
                                    4. check endpoint allowlist               + X-Service-Secret
                                    5. forward + log + time                    and returns data
                                    6. pipe response back                    ◀─────────────────
```

## Repository layout

```
app.py                    Flask entrypoint (gunicorn app:app)
meteorbase/
  db.py                   Supabase client (service_role) singleton
  security.py             X-API-Key + JWT admin decorators, rate limiting
  registry.py             public metadata: /api/v1/apps, /apps/<name>, /me
  proxy.py                the gateway proxy + /apps/<name>/heartbeat
  admin.py                admin CRUD for services, endpoints, logs, heartbeats
supabase/schema.sql       full schema + RLS (run in Supabase SQL Editor)
docs/INTEGRATION_GUIDE.md how to wire your apps in as webhooks
examples/
  webhook_receiver.py     receiver template for any child app
  meteorbase_client.py    Python client for calling the gateway
templates/                landing / auth / dashboard
```

## Setup

1. **Supabase** — run `supabase/schema.sql` in the Supabase SQL Editor.
2. **Environment** — copy `.env.example` to `.env` and fill in:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_KEY` (service_role — required so the server can read secrets + write logs)
   - `SUPABASE_JWT_SECRET`
   - `INTERNAL_SECRET` (a long random string shared with all your apps)
3. **Run**
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
   → http://localhost:5000

   For Render, use `pip install -r requirements.txt` as the build command and `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 30 app:app` as the start command. The included `render.yaml` declares the same setup and uses `/healthz` for process health. Configure every required environment variable in Render; never commit a `.env` file.
4. **Sign in**, generate an API key, and register your first app (Oblivion, VEX, ...).
5. Follow `docs/INTEGRATION_GUIDE.md` to wire the app's webhook receiver.

## API surface

```
# Public (metadata, no auth)
GET  /api/v1/apps
GET  /api/v1/apps/<name>
GET  /api/v1/apps/<name>/endpoints
GET  /api/v1/me
GET  /healthz                          # Render liveness
GET  /readyz                           # Supabase and configuration readiness

# Gateway (requires X-API-Key)
ANY  /api/v1/<app_name>/<path>        # proxied to the registered webhook
POST /api/v1/apps/<name>/heartbeat    # uptime ping (X-Service-Secret)

# Admin (requires admin JWT)
GET/POST/PATCH/DELETE /api/v1/admin/services...
GET  /api/v1/admin/logs
GET  /api/v1/admin/heartbeats
```

## Security model

- **Users** authenticate with Supabase Auth (email, Google, GitHub, OTP).
- **Machines** authenticate with `X-API-Key` (revocable, expirable, rate-limited).
- **App access** is scoped via `api_key_service_access` (empty = all apps).
- **Endpoints** are allowlisted via `service_endpoints` metadata.
- **Server → app** traffic is authenticated with `X-Internal-Secret` + `X-Service-Secret`.
- **Admin controls** are enforced server-side from `profiles.role`.
- `webhook_secret` is column-level locked so the browser can never read it.

## Notes

- Keys generated in the dashboard are stored raw in `api_keys` (hashed/enveloped variants can be
  added later). Displayed to the user exactly once as `mb_live_...`.
- The gateway runs in "open mode" for a service until you register its endpoint metadata.
