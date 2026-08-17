# MeteorBase - Integration Guide for Your Apps

MeteorBase is **not** a note-taking app. It is the **control plane** for
every app you build: VEX, SkipIdeate, Oblivion, and everything after them.

Each of your apps keeps its own business logic, routes, and database. The
app simply exposes a **webhook receiver**, and MeteorBase becomes the only
API a client ever talks to.

```
 CLIENT APP                          METEORBASE (this repo)                    YOUR APP
 (your code / your users)            gateway + Supabase                        e.g. Oblivion
 ┌─────────────────┐                 ┌──────────────────────────┐             ┌────────────────────┐
 │ X-API-Key: mb…  │  ───────────▶   │ 1. validate API key       │             │  webhook receiver  │
 │                 │                 │ 2. look up app in DB      │──────────▶  │  (HTTP endpoint)   │
 │  GET /api/v1/   │                 │ 3. check key scope        │  forward    │  validates         │
 │  oblivion/      │  ◀───────────   │ 4. validate endpoint meta │  with       │  X-Internal-Secret │
 │  sessions       │                 │ 5. forward + log + time   │  secrets    │  X-Service-Secret  │
 └─────────────────┘                 └────────────┬─────────────┘  ◀──────────  └────────────────────┘
                                                  │  X-User-ID                  └───────┬────────────┘
                                                  └── record logs / heartbeat ◀────────┘
                                                        (uptime ping every few minutes)
```

Everything is driven by **real rows in Supabase** — nothing is hardcoded.
An app name, its webhook URL, its endpoints, and its secret all live in the
database and are edited from the dashboard / admin API.

---

## Part 1 - Register an app in MeteorBase

1. Sign in at `/dashboard` with your owner account (it becomes `admin`
   automatically).
2. In **Register New Microservice**:
   - **App / Service Name** — a unique slug, e.g. `oblivion` (this is the
     name used in the URL, so keep it lowercase).
   - **Display Name** — `Oblivion`.
   - **Target Webhook Base URL** — the base URL of your app's receiver,
     e.g. `https://oblivion-api.onrender.com`.
3. Click **REGISTER**. A `webhook_secret` is issued. **Copy it and put it in
   the app's environment** (never in the browser / public code).

   > The gateway stores this secret in `services.webhook_secret`. It is
   > column-level locked so only the gateway server (and admins via the
   > dashboard) can ever read it back.

4. Add the app's allowed routes under **endpoint metadata** (the service card
   in the dashboard has an *ADD* form): `POST /sessions`, `GET /sessions`,
   `DELETE /sessions/{id}`, etc. MeteorBase then **rejects any request that
   is not in this list**.
   - Until you register endpoints, the app runs in **open mode** (any route
     passes) so you can bootstrap quickly.

---

## Part 2 - Implement the webhook receiver in your app

Your app is the source of truth for its own data. Add a small receiver to it:

```python
# inside Oblivion (or VEX, SkipIdeate, ...)
from functools import wraps
from flask import Flask, request, jsonify

app = Flask(__name__)

# Same value in EVERY app + in MeteorBase's .env
INTERNAL_SECRET = os.environ["INTERNAL_SECRET"]
# Unique per app, from the MeteorBase dashboard after registration
WEBHOOK_SECRET = os.environ["MB_WEBHOOK_SECRET"]

def require_meteorbase(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Internal-Secret") != INTERNAL_SECRET:
            return jsonify({"error": "forbidden"}), 403
        if request.headers.get("X-Service-Secret") != WEBHOOK_SECRET:
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)
    return wrapper

@app.route("/sessions", methods=["GET", "POST"])
@require_meteorbase
def sessions():
    user_id = request.headers.get("X-User-ID")  # the MeteorBase user calling
    # ... your real logic, scoped to user_id ...
    return jsonify({"sessions": [...]})
```

Key headers MeteorBase always forwards to your app:

| Header              | Meaning                                                        |
| ------------------- | -------------------------------------------------------------- |
| `X-Internal-Secret` | Proves the request came from MeteorBase (shared, same everywhere) |
| `X-Service-Secret`  | The app's own webhook_secret (per-app)                         |
| `X-User-ID`         | The MeteorBase user making the call — **scope data to this**   |

Rules:

- **Always** trust `X-User-ID` over the body for authorization.
- Your app's other clients (own dashboard, internal tooling) can call your
  receiver directly, but external/public traffic should only go through
  MeteorBase.

---

## Part 3 - Clients call MeteorBase (not your app)

From any of your client apps or server code:

```bash
curl https://your-meteorbase.onrender.com/api/v1/oblivion/sessions \
  -H "X-API-Key: mb_live_<your-key>"
```

```python
import requests

r = requests.get(
    "https://your-meteorbase.onrender.com/api/v1/oblivion/sessions",
    headers={"X-API-Key": "mb_live_<your-key>"},
)
print(r.json())
```

```js
const res = await fetch(
  "https://your-meteorbase.onrender.com/api/v1/oblivion/sessions",
  { headers: { "X-API-Key": "mb_live_<your-key>" } }
);
```

The URL pattern is always:

```
METHOD /api/v1/<app_name>/<rest of the path inside your app>
```

Any HTTP method, query params, and JSON body pass straight through. See
`examples/meteorbase_client.py` for a reusable client.

---

## Part 4 - Apps ping MeteorBase for uptime

In each app, run a periodic job (cron / APScheduler / Celery beat) that
pings MeteorBase so the dashboard can show live health:

```python
import requests

requests.post(
    "https://your-meteorbase.onrender.com/api/v1/apps/oblivion/heartbeat",
    headers={"X-Service-Secret": os.environ["MB_WEBHOOK_SECRET"]},
    json={"status": "ok", "latency_ms": 12, "details": {"version": "2.1.0"}},
    timeout=10,
)
```

MeteorBase records the ping in `service_heartbeats` and stamps
`services.last_seen_at`. If an app stops pinging, the dashboard shows
**NEVER** / stale on its card.

---

## Security model (summary)

| Layer                 | Where                                          |
| --------------------- | ---------------------------------------------- |
| User authentication   | Supabase Auth (email, Google, GitHub, OTP)     |
| Machine auth          | `api_keys` + `X-API-Key` header                |
| App access scoping    | `api_key_service_access` (empty = all apps)    |
| Endpoint allowlist    | `service_endpoints` metadata                   |
| Server → app auth     | `X-Internal-Secret` + `X-Service-Secret`       |
| Uptime auth           | `X-Service-Secret` on `/heartbeat`             |
| Data isolation        | Your apps scope everything by `X-User-ID`      |
| Admin controls        | `profiles.role = 'admin'`, validated server-side |

---

## Admin API reference

Everything the dashboard does is available as an API. These require an
`Authorization: Bearer <your-supabase-jwt>` header from an admin account:

| Method | Path                                     | Purpose                         |
| ------ | ---------------------------------------- | ------------------------------- |
| GET    | `/api/v1/admin/services`                 | List apps + endpoints           |
| POST   | `/api/v1/admin/services`                 | Register an app                 |
| PATCH  | `/api/v1/admin/services/<id>`            | Update / toggle active          |
| DELETE | `/api/v1/admin/services/<id>`            | Unregister an app               |
| POST   | `/api/v1/admin/services/<id>/endpoints`  | Add endpoint metadata           |
| DELETE | `/api/v1/admin/services/<id>/endpoints/<eid>` | Remove an endpoint         |
| GET    | `/api/v1/admin/logs`                     | Request logs                    |
| GET    | `/api/v1/admin/heartbeats`               | Uptime pings                    |

Public metadata (no auth) for discovering what's available:

| Method | Path                        | Purpose                        |
| ------ | --------------------------- | ------------------------------ |
| GET    | `/api/v1/apps`              | List registered apps (safe cols) |
| GET    | `/api/v1/apps/<name>`       | One app's metadata             |
| GET    | `/api/v1/apps/<name>/endpoints` | Declared endpoint metadata  |
| GET    | `/api/v1/me`                | Current profile (role)         |

---

## Checking it works end-to-end

1. Register `oblivion` in the dashboard (get its secret).
2. Run `examples/webhook_receiver.py` locally with those secrets.
3. Generate an API key in the dashboard.
4. Call:
   ```bash
   curl http://localhost:5000/api/v1/oblivion/health \
     -H "X-API-Key: mb_live_<key>"
   ```
5. Watch the row appear in **Gateway Request Logs** on the dashboard.
