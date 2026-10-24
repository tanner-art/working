-- Installation script: additive, transactional, no capture/account tables touched.
-- No spending is enabled by installation. Provision policy after accounting for prior spend.
begin;
create table public.threadline_ai_budget_policy (
  singleton boolean primary key default true check (singleton),
  enabled boolean not null default false,
  monthly_limit_micros bigint not null default 5000000 check (monthly_limit_micros between 0 and 5000000)
);
insert into public.threadline_ai_budget_policy(singleton) values (true);
create table public.threadline_ai_budget_months (
  month date primary key,
  committed_micros bigint not null check (committed_micros between 0 and 5000000)
);
create table public.threadline_ai_spend_reservations (
  id uuid primary key,
  month date not null references public.threadline_ai_budget_months(month),
  reserved_micros bigint not null check (reserved_micros between 1 and 612000),
  settled_micros bigint check (settled_micros between 0 and reserved_micros),
  created_at timestamptz not null default now(),
  settled_at timestamptz
);
alter table public.threadline_ai_budget_policy enable row level security;
alter table public.threadline_ai_budget_months enable row level security;
alter table public.threadline_ai_spend_reservations enable row level security;
revoke all on public.threadline_ai_budget_policy, public.threadline_ai_budget_months, public.threadline_ai_spend_reservations from public, anon, authenticated, service_role;
grant select on public.threadline_ai_budget_policy to service_role;
grant select, insert, update on public.threadline_ai_budget_months, public.threadline_ai_spend_reservations to service_role;

create function public.threadline_reserve_ai_spend(p_id uuid, p_micros bigint)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  budget bigint;
  carried bigint;
  period date := date_trunc('month', statement_timestamp() at time zone 'UTC')::date;
begin
  if p_id is null or p_micros is null or p_micros < 600010 or p_micros > 612000 then return 'invalid'; end if;
  perform pg_catalog.pg_advisory_xact_lock(88421, 5);
  select monthly_limit_micros into budget from public.threadline_ai_budget_policy where singleton and enabled;
  if budget is null then return 'disabled'; end if;
  insert into public.threadline_ai_budget_months values (period, 0) on conflict do nothing;
  -- Transaction advisory lock serializes across UTC rollover/users/instances.
  perform 1 from public.threadline_ai_budget_months where month = period for update;
  select coalesce(sum(reserved_micros), 0) into carried from public.threadline_ai_spend_reservations where month <> period and settled_micros is null;
  if exists(select 1 from public.threadline_ai_spend_reservations where id = p_id) then return 'duplicate'; end if;
  update public.threadline_ai_budget_months set committed_micros = committed_micros + p_micros
    where month = period and committed_micros + carried + p_micros <= budget;
  if not found then return 'exhausted'; end if;
  insert into public.threadline_ai_spend_reservations(id, month, reserved_micros) values (p_id, period, p_micros);
  return 'reserved';
end $$;

create function public.threadline_settle_ai_spend(p_id uuid, p_micros bigint)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  r public.threadline_ai_spend_reservations;
  period date := date_trunc('month', statement_timestamp() at time zone 'UTC')::date;
begin
  perform pg_catalog.pg_advisory_xact_lock(88421, 5);
  select * into r from public.threadline_ai_spend_reservations where id = p_id;
  if not found or p_micros is null or p_micros < 0 or p_micros > r.reserved_micros then return false; end if;
  perform 1 from public.threadline_ai_budget_months where month = r.month for update;
  select * into r from public.threadline_ai_spend_reservations where id = p_id for update;
  if r.settled_micros is not null then return r.settled_micros = p_micros; end if;
  update public.threadline_ai_budget_months set committed_micros = committed_micros - r.reserved_micros + p_micros where month = r.month;
  -- A reply crossing UTC month-end is conservatively charged in BOTH months.
  -- Until settlement its entire old reservation also reduced the new allowance.
  if period <> r.month then
    insert into public.threadline_ai_budget_months values (period, p_micros)
      on conflict (month) do update set committed_micros = public.threadline_ai_budget_months.committed_micros + excluded.committed_micros;
  end if;
  update public.threadline_ai_spend_reservations set settled_micros = p_micros, settled_at = now() where id = p_id;
  return true;
end $$;
revoke all on function public.threadline_reserve_ai_spend(uuid, bigint), public.threadline_settle_ai_spend(uuid, bigint) from public, anon, authenticated;
grant execute on function public.threadline_reserve_ai_spend(uuid, bigint), public.threadline_settle_ai_spend(uuid, bigint) to service_role;
commit;
