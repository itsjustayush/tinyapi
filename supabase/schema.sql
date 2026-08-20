-- MeteorBase secure gateway schema
-- Run in the Supabase SQL editor. The gateway uses the service-role key server-side.

create extension if not exists "pgcrypto";

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  role text not null default 'user' check (role in ('user', 'admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email) values (new.id, new.email)
  on conflict (id) do update set email = excluded.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create table if not exists public.services (
  id uuid primary key default gen_random_uuid(),
  name text unique not null check (name ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'),
  display_name text not null,
  description text,
  webhook_url text not null,
  webhook_secret text not null,
  is_active boolean not null default true,
  owner_user_id uuid references auth.users(id) on delete set null,
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.service_endpoints (
  id uuid primary key default gen_random_uuid(),
  service_id uuid not null references public.services(id) on delete cascade,
  method text not null check (method in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS')),
  path text not null check (left(path, 1) = '/'),
  description text,
  requires_auth boolean not null default true,
  created_at timestamptz not null default now(),
  unique (service_id, method, path)
);

create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null default 'default',
  key_hash text unique not null,
  key_prefix text not null,
  is_active boolean not null default true,
  expires_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists api_keys_user_idx on public.api_keys(user_id);
create index if not exists api_keys_hash_idx on public.api_keys(key_hash);

create table if not exists public.api_key_service_access (
  id uuid primary key default gen_random_uuid(),
  api_key_id uuid not null references public.api_keys(id) on delete cascade,
  service_id uuid not null references public.services(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (api_key_id, service_id)
);

create table if not exists public.request_logs (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  api_key_id uuid references public.api_keys(id) on delete set null,
  service_id uuid references public.services(id) on delete set null,
  service_name text,
  method text not null,
  path text not null,
  status_code int not null default 0,
  latency_ms int not null default 0,
  remote_ip text,
  created_at timestamptz not null default now()
);
create index if not exists request_logs_service_idx on public.request_logs(service_name, created_at desc);
create index if not exists request_logs_user_idx on public.request_logs(user_id, created_at desc);

create table if not exists public.service_heartbeats (
  id bigint generated always as identity primary key,
  service_id uuid not null references public.services(id) on delete cascade,
  status text not null default 'ok',
  latency_ms int not null default 0,
  details jsonb,
  created_at timestamptz not null default now()
);
create index if not exists service_heartbeats_svc_idx on public.service_heartbeats(service_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at before update on public.profiles for each row execute function public.set_updated_at();
drop trigger if exists services_set_updated_at on public.services;
create trigger services_set_updated_at before update on public.services for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.services enable row level security;
alter table public.service_endpoints enable row level security;
alter table public.api_keys enable row level security;
alter table public.api_key_service_access enable row level security;
alter table public.request_logs enable row level security;
alter table public.service_heartbeats enable row level security;

create or replace function public.is_admin()
returns boolean
language sql
security definer set search_path = public
stable
as $$
  select exists(select 1 from public.profiles where id = auth.uid() and role = 'admin');
$$;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles for select to authenticated using (auth.uid() = id);
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);
drop policy if exists profiles_select_admin on public.profiles;
create policy profiles_select_admin on public.profiles for select to authenticated using (public.is_admin());

drop policy if exists services_read_authed on public.services;
create policy services_read_authed on public.services for select to authenticated using (is_active = true or public.is_admin());
drop policy if exists services_write_admin on public.services;
create policy services_write_admin on public.services for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists endpoints_read_authed on public.service_endpoints;
create policy endpoints_read_authed on public.service_endpoints for select to authenticated using (true);
drop policy if exists endpoints_write_admin on public.service_endpoints;
create policy endpoints_write_admin on public.service_endpoints for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists api_keys_none_from_browser on public.api_keys;
create policy api_keys_none_from_browser on public.api_keys for all to authenticated using (false) with check (false);
drop policy if exists key_access_none_from_browser on public.api_key_service_access;
create policy key_access_none_from_browser on public.api_key_service_access for all to authenticated using (false) with check (false);

drop policy if exists logs_select_own on public.request_logs;
create policy logs_select_own on public.request_logs for select to authenticated using (user_id = auth.uid());
drop policy if exists logs_select_admin on public.request_logs;
create policy logs_select_admin on public.request_logs for select to authenticated using (public.is_admin());

drop policy if exists heartbeats_read_authed on public.service_heartbeats;
create policy heartbeats_read_authed on public.service_heartbeats for select to authenticated using (true);

-- After the first account signs in, promote your admin account:
-- update public.profiles set role = 'admin' where email = 'you@example.com';
