-- ============================================================
-- METEORBASE - Unified API Gateway Schema
-- ------------------------------------------------------------
-- Run this file in the Supabase SQL Editor (or: supabase db push)
-- Every table below is backed by REAL registered data. Nothing
-- here is hardcoded into the gateway code; all app names,
-- webhook URLs and endpoint metadata are inserted at runtime
-- through the admin API / dashboard.
--
-- Roles used by RLS:
--   * authenticated - any logged-in MeteorBase user
--   * service_role  - the gateway server itself (bypasses RLS)
--   * admin profile - users with profiles.role = 'admin'
-- ============================================================

create extension if not exists "pgcrypto";

-- ------------------------------------------------------------
-- PROFILES (extends auth.users)
-- ------------------------------------------------------------
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text,
  role        text not null default 'user' check (role in ('user', 'admin')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Auto-create a profile when a user signs up.
-- NOTE: the first/owner account is promoted to admin automatically.
-- Change the email below if your owner account differs.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, role)
  values (
    new.id,
    new.email,
    case when lower(new.email) = 'info.cometlabs@gmail.com' then 'admin' else 'user' end
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ------------------------------------------------------------
-- SERVICES - every app you own is registered here once.
--   name          -> unique slug, e.g. 'oblivion', 'vex', 'skipideate'
--   webhook_url   -> base URL of that app's MeteorBase receiver
--   webhook_secret-> shared secret MeteorBase sends to that app
--   last_seen_at  -> set by the app's heartbeat pings (uptime)
-- ------------------------------------------------------------
create table if not exists public.services (
  id             uuid primary key default gen_random_uuid(),
  name           text unique not null,
  display_name   text,
  description    text,
  webhook_url    text not null,
  webhook_secret text not null default replace(gen_random_uuid()::text, '-', ''),
  is_active      boolean not null default true,
  owner_user_id  uuid references auth.users(id) on delete set null,
  last_seen_at   timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- ------------------------------------------------------------
-- SERVICE ENDPOINTS - the declared routes/methods of each app.
-- MeteorBase validates incoming requests against this metadata,
-- so the gateway rejects anything not explicitly allowed.
-- (If a service has no rows here yet, the gateway runs in open
--  mode so you can bootstrap an app quickly.)
-- ------------------------------------------------------------
create table if not exists public.service_endpoints (
  id            uuid primary key default gen_random_uuid(),
  service_id    uuid not null references public.services(id) on delete cascade,
  method        text not null check (method in ('GET','POST','PUT','PATCH','DELETE')),
  path          text not null,                 -- e.g. '/sessions' or '/api/v1/sessions'
  description   text,
  requires_auth boolean not null default true,
  created_at    timestamptz not null default now(),
  unique (service_id, method, path)
);

-- ------------------------------------------------------------
-- API KEYS - one per user, used in the X-API-Key header.
-- ------------------------------------------------------------
create table if not exists public.api_keys (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null default 'default',
  api_key       text unique not null,
  is_active     boolean not null default true,
  expires_at    timestamptz,
  last_used_at  timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists api_keys_user_idx on public.api_keys(user_id);

-- ------------------------------------------------------------
-- KEY -> SERVICE ACCESS - which services a key may call.
-- An empty set for a key means "access to every registered app".
-- ------------------------------------------------------------
create table if not exists public.api_key_service_access (
  id         uuid primary key default gen_random_uuid(),
  api_key_id uuid not null references public.api_keys(id) on delete cascade,
  service_id uuid not null references public.services(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (api_key_id, service_id)
);

-- ------------------------------------------------------------
-- REQUEST LOGS - full gateway traffic telemetry.
-- Written by the gateway (service_role); read by owner / admin.
-- ------------------------------------------------------------
create table if not exists public.request_logs (
  id           bigint generated always as identity primary key,
  user_id      uuid,
  api_key_id   uuid,
  service_id   uuid,
  service_name text,
  method       text not null,
  path         text not null,
  status_code  int not null default 0,
  latency_ms   int not null default 0,
  remote_ip    text,
  created_at   timestamptz not null default now()
);
create index if not exists request_logs_service_idx on public.request_logs(service_name, created_at desc);
create index if not exists request_logs_user_idx   on public.request_logs(user_id, created_at desc);

-- ------------------------------------------------------------
-- SERVICE HEARTBEATS - uptime pings pushed by each app.
-- ------------------------------------------------------------
create table if not exists public.service_heartbeats (
  id         bigint generated always as identity primary key,
  service_id uuid not null references public.services(id) on delete cascade,
  status     text not null default 'ok',
  latency_ms int not null default 0,
  details    jsonb,
  created_at timestamptz not null default now()
);
create index if not exists service_heartbeats_svc_idx on public.service_heartbeats(service_id, created_at desc);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

alter table public.profiles             enable row level security;
alter table public.services             enable row level security;
alter table public.service_endpoints    enable row level security;
alter table public.api_keys             enable row level security;
alter table public.api_key_service_access enable row level security;
alter table public.request_logs         enable row level security;
alter table public.service_heartbeats   enable row level security;

-- Helper: is the current (authenticated) user an admin?
create or replace function public.is_admin()
returns boolean
language sql
security definer set search_path = public
stable
as $$
  select exists(
    select 1 from public.profiles p
    where p.id = auth.uid() and p.role = 'admin'
  );
$$;

-- ---- PROFILES ----
create policy "profiles_select_own"   on public.profiles for select to authenticated using (auth.uid() = id);
create policy "profiles_update_own"   on public.profiles for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);
create policy "profiles_select_admin" on public.profiles for select to authenticated using (public.is_admin());

-- ---- SERVICES ----
-- Readable by any logged-in user (safe columns only - see grants below).
-- All writes (register / update / delete) are admin-only.
create policy "services_read_authed" on public.services
  for select to authenticated using (true);
create policy "services_write_admin" on public.services
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

-- Hide the internal webhook_secret from non-admins at the COLUMN level.
revoke select (webhook_secret) on public.services from anon, authenticated;

-- ---- SERVICE ENDPOINTS ----
create policy "endpoints_read_authed" on public.service_endpoints
  for select to authenticated using (true);
create policy "endpoints_write_admin" on public.service_endpoints
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

-- ---- API KEYS (users manage their own) ----
create policy "api_keys_select_own" on public.api_keys
  for select to authenticated using (auth.uid() = user_id);
create policy "api_keys_insert_own" on public.api_keys
  for insert to authenticated with check (auth.uid() = user_id);
create policy "api_keys_update_own" on public.api_keys
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "api_keys_delete_own" on public.api_keys
  for delete to authenticated using (auth.uid() = user_id);

-- ---- KEY ACCESS (users manage the scopes of their own keys) ----
create policy "key_access_select_own" on public.api_key_service_access
  for select to authenticated using (
    exists (select 1 from public.api_keys k where k.id = api_key_id and k.user_id = auth.uid())
  );
create policy "key_access_insert_own" on public.api_key_service_access
  for insert to authenticated with check (
    exists (select 1 from public.api_keys k where k.id = api_key_id and k.user_id = auth.uid())
  );
create policy "key_access_delete_own" on public.api_key_service_access
  for delete to authenticated using (
    exists (select 1 from public.api_keys k where k.id = api_key_id and k.user_id = auth.uid())
  );

-- ---- REQUEST LOGS (owner sees own, admin sees all; writes via service_role) ----
create policy "logs_select_own"   on public.request_logs for select to authenticated using (user_id = auth.uid());
create policy "logs_select_admin" on public.request_logs for select to authenticated using (public.is_admin());

-- ---- HEARTBEATS (readable; written by the gateway via service_role) ----
create policy "heartbeats_read_authed" on public.service_heartbeats
  for select to authenticated using (true);

-- ------------------------------------------------------------
-- updated_at helper
-- ------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists services_set_updated_at on public.services;
create trigger services_set_updated_at
  before update on public.services
  for each row execute function public.set_updated_at();