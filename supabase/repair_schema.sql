-- METEORBASE PRODUCTION SCHEMA REPAIR
-- Run this once in the Supabase SQL Editor for the project configured in Render.
-- It upgrades an earlier minimal `services` table and creates the remaining
-- gateway tables required by the current Render deployment. It does not seed
-- services, API keys, webhook URLs, or any other application data.

create extension if not exists "pgcrypto";

alter table public.profiles
  add column if not exists email text,
  add column if not exists role text not null default 'user',
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

alter table public.services
  add column if not exists display_name text,
  add column if not exists description text,
  add column if not exists webhook_url text,
  add column if not exists webhook_secret text default replace(gen_random_uuid()::text, '-', ''),
  add column if not exists is_active boolean not null default true,
  add column if not exists owner_user_id uuid references auth.users(id) on delete set null,
  add column if not exists last_seen_at timestamptz,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

create table if not exists public.service_endpoints (
  id uuid primary key default gen_random_uuid(),
  service_id uuid not null references public.services(id) on delete cascade,
  method text not null check (method in ('GET','POST','PUT','PATCH','DELETE')),
  path text not null,
  description text,
  requires_auth boolean not null default true,
  created_at timestamptz not null default now(),
  unique (service_id, method, path)
);

create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null default 'default',
  api_key text unique not null,
  is_active boolean not null default true,
  expires_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.api_key_service_access (
  id uuid primary key default gen_random_uuid(),
  api_key_id uuid not null references public.api_keys(id) on delete cascade,
  service_id uuid not null references public.services(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (api_key_id, service_id)
);

create table if not exists public.request_logs (
  id bigint generated always as identity primary key,
  user_id uuid,
  api_key_id uuid,
  service_id uuid,
  service_name text,
  method text not null,
  path text not null,
  status_code int not null default 0,
  latency_ms int not null default 0,
  remote_ip text,
  created_at timestamptz not null default now()
);

create table if not exists public.service_heartbeats (
  id bigint generated always as identity primary key,
  service_id uuid not null references public.services(id) on delete cascade,
  status text not null default 'ok',
  latency_ms int not null default 0,
  details jsonb,
  created_at timestamptz not null default now()
);

create index if not exists api_keys_user_idx on public.api_keys(user_id);
create index if not exists request_logs_service_idx on public.request_logs(service_name, created_at desc);
create index if not exists request_logs_user_idx on public.request_logs(user_id, created_at desc);
create index if not exists service_heartbeats_svc_idx on public.service_heartbeats(service_id, created_at desc);

-- Apply the RLS policies, trigger, and column grants from `schema.sql` after
-- this repair. Those policies are intentionally kept in the main schema file.
