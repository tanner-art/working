-- One replaceable, read-only copy of the Mac Registry projection.
-- Base64 expands the accepted 1 MiB compressed body to at most 1,398,104 bytes.
-- Apply through the Supabase migration workflow before enabling the publisher.
create table if not exists public.factory_dashboard_snapshot (
  id text primary key check (id = 'current'),
  body text not null check (octet_length(body) <= 1398104),
  signature text not null check (signature ~ '^sha256=[0-9a-f]{64}$'),
  registry_revision text not null,
  published_at timestamptz not null default now()
);

alter table public.factory_dashboard_snapshot enable row level security;
revoke all on table public.factory_dashboard_snapshot from anon, authenticated;
-- The server-only service role is the sole reader/writer. No browser Data API access.
