# Supabase privilege review — 2026-09-24

Work package: `RISK-001`  
Lane: `PLATFORM` with security-oriented `ASSURANCE` review  
Status: approved legacy-table privilege reduction applied and verified

## Scope and evidence boundary

This review queried PostgreSQL catalog metadata in the existing Threadline Supabase project. It did not read account rows, authentication records, credentials, or user content. The application code was inspected to identify the operations used by the current account-data path.

The current application creates its adapter from `VITE_SUPABASE_DATA_TABLE` and performs only:

- `SELECT` by `user_id`;
- create-only `UPSERT` for the first account copy; and
- optimistic `UPDATE` by `user_id` and `revision`.

It has no account-data `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` operation. Current production documentation identifies `public.threadline_account_data` as the configured table. The legacy `public.threadline_user_state` name is absent from application source.

## Live catalog evidence before remediation

Both public tables have row-level security enabled.

| Table | Role | SELECT | INSERT | UPDATE | DELETE | TRUNCATE | REFERENCES | TRIGGER |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `threadline_account_data` | `authenticated` | yes | yes | yes | no | no | no | no |
| `threadline_account_data` | `anon` | no | no | no | no | no | no | no |
| `threadline_user_state` (legacy) | `authenticated` | yes | yes | yes | yes | yes | yes | yes |
| `threadline_user_state` (legacy) | `anon` | yes | yes | yes | yes | yes | yes | yes |

`threadline_account_data` has owner-scoped `SELECT`, `INSERT`, and `UPDATE` policies for `authenticated`. It already matches the application's minimum privilege set. The earlier blocker text that attributed four excess signed-in grants to this table was stale.

`threadline_user_state` has owner-scoped policies for `authenticated`, including a legacy `DELETE` policy. It has no anonymous policies, so RLS denies anonymous row-level `SELECT`, `INSERT`, `UPDATE`, and `DELETE` operations. RLS does **not** constrain whole-table `TRUNCATE`, schema-level `REFERENCES`, or `TRIGGER` privileges. Those anonymous grants are therefore a separate elevated legacy-table risk.

## Bounded remediation applied

No change is required or appropriate on `threadline_account_data`.

The requested signed-in privilege reduction applies to the unused legacy table:

```sql
revoke delete, truncate, references, trigger
on table public.threadline_user_state
from authenticated;
```

The product owner explicitly approved this exact reduction on 2026-09-24. It was applied through the Supabase migration boundary as `reduce_authenticated_legacy_threadline_privileges`. No other role, table, grant, policy, or row was changed.

## Live catalog evidence after remediation

The post-change catalog query returned:

| Table | Role | SELECT | INSERT | UPDATE | DELETE | TRUNCATE | REFERENCES | TRIGGER |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `threadline_account_data` | `authenticated` | yes | yes | yes | no | no | no | no |
| `threadline_account_data` | `anon` | no | no | no | no | no | no | no |
| `threadline_user_state` (legacy) | `authenticated` | yes | yes | yes | no | no | no | no |
| `threadline_user_state` (legacy) | `anon` | yes | yes | yes | yes | yes | yes | yes |

Both tables remain RLS-enabled. Their policies are unchanged. The legacy authenticated DELETE policy remains defined but is no longer usable by `authenticated` because the table-level DELETE grant was revoked.

Anonymous grants on the legacy table are documented as a separate residual risk. RLS and the absence of anonymous policies constrain its row-level grants, but do not protect `TRUNCATE`, `REFERENCES`, or `TRIGGER`. Removing those grants or retiring the table requires an explicit retention/compatibility decision and is outside this signed-in-role work package.

## Target least-privilege state

- `threadline_account_data`: authenticated `SELECT`, `INSERT`, and `UPDATE`; no anonymous grants; owner-only RLS policies.
- `threadline_user_state`: authenticated `SELECT`, `INSERT`, and `UPDATE` while compatibility is retained; no authenticated `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` grants.
- Legacy anonymous grants: separately decide between revocation and table retirement after confirming no supported legacy client depends on the table.

## Verification completed and remaining release validation

Completed:

1. Applied the single approved `REVOKE` migration through the Supabase migration boundary.
2. Re-ran `information_schema.role_table_grants`; authenticated now retains only SELECT, INSERT, and UPDATE on both tables.
3. Confirmed both tables still have RLS enabled and their policies are unchanged.
4. Confirmed current create/load/save/conflict paths remain supported by the retained grants; the pre-change focused account-storage/cloud-data/auth suite passed, and the post-change full repository check passed all 649 tests, the application build, and the API typecheck.
5. Ran Supabase security advisors after the migration.

Remaining release validation is the two-account/two-device RLS exercise described in `docs/ACCOUNT_LEVEL_BLOCKERS.md`; catalog metadata alone cannot certify that end-to-end behavior.

The live security advisor currently reports only that leaked-password protection is disabled. Threadline's active sign-in flow is passwordless email code/link; that advisor item is not caused by this grant work.

## Reproducible catalog queries

The before matrix was generated from these read-only catalog queries. The result was manually reduced to table, role, and boolean privilege values; no row data or identifiers were selected.

```sql
select table_schema, table_name, grantee, privilege_type, is_grantable
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated')
order by table_name, grantee, privilege_type;
```

```sql
select jsonb_build_object(
  'select', has_table_privilege('authenticated', 'public.threadline_user_state', 'SELECT'),
  'insert', has_table_privilege('authenticated', 'public.threadline_user_state', 'INSERT'),
  'update', has_table_privilege('authenticated', 'public.threadline_user_state', 'UPDATE'),
  'delete', has_table_privilege('authenticated', 'public.threadline_user_state', 'DELETE'),
  'truncate', has_table_privilege('authenticated', 'public.threadline_user_state', 'TRUNCATE'),
  'references', has_table_privilege('authenticated', 'public.threadline_user_state', 'REFERENCES'),
  'trigger', has_table_privilege('authenticated', 'public.threadline_user_state', 'TRIGGER')
);
```

RLS state and policy commands were read from `pg_class`, `pg_namespace`, and `pg_policies`. The queries were run immediately before and after the approved production migration; this document records the reduced evidence rather than user data or identifiers.
