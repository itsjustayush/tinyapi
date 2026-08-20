-- One-time migration for existing MeteorBase deployments.
-- Run this before applying the new schema policies if api_keys still has raw api_key values.

alter table if exists public.api_keys add column if not exists key_hash text;
alter table if exists public.api_keys add column if not exists key_prefix text;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'api_keys' AND column_name = 'api_key'
  ) THEN
    EXECUTE 'update public.api_keys set key_hash = encode(digest(api_key, ''sha256''), ''hex''), key_prefix = left(api_key, 17) where key_hash is null';
    EXECUTE 'alter table public.api_keys drop column api_key';
  END IF;
END $$;

update public.api_keys
set key_prefix = coalesce(key_prefix, 'mb_live_legacy'),
    key_hash = coalesce(key_hash, encode(digest(gen_random_uuid()::text, 'sha256'), 'hex'))
where key_prefix is null or key_hash is null;

alter table public.api_keys alter column key_hash set not null;
alter table public.api_keys alter column key_prefix set not null;
create unique index if not exists api_keys_key_hash_uidx on public.api_keys(key_hash);
