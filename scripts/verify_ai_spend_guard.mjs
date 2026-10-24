// Synthetic SQL verification. Run with a local PostgreSQL-compatible PGlite install:
// PGLITE_MODULE=/absolute/path/to/@electric-sql/pglite/dist/index.js node scripts/verify_ai_spend_guard.mjs
import { readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'
const { PGlite } = await import(pathToFileURL(process.env.PGLITE_MODULE).href)
const db = new PGlite()
await db.exec('create role anon; create role authenticated; create role service_role bypassrls;')
await db.exec(await readFile(new URL('./ai_spend_guard.sql', import.meta.url), 'utf8'))
const call = async (fn, id, cost) => (await db.query(`select public.${fn}($1::uuid,$2::bigint) as result`, [id, cost])).rows[0].result
const reserve = (id, cost = 612000) => call('threadline_reserve_ai_spend', id, cost)
const settle = (id, cost) => call('threadline_settle_ai_spend', id, cost)
assert.equal(await reserve(randomUUID()), 'disabled')
await db.exec('update public.threadline_ai_budget_policy set enabled = true; set role service_role;')
const ids = Array.from({length: 10}, () => randomUUID())
// Concurrent callers against the real SQL implementation (PGlite queues its one connection).
const outcomes = await Promise.all(ids.map(id => reserve(id)))
assert.equal(outcomes.filter(x => x === 'reserved').length, 8)
assert.equal(outcomes.filter(x => x === 'exhausted').length, 2)
assert.equal(await reserve(ids[0]), 'duplicate')
assert.equal(await settle(ids[0], 400), true)
assert.equal(await settle(ids[0], 400), true)
assert.equal(await settle(ids[0], 0), false)
assert.equal(await settle(ids[1], -1), false)
assert.equal(await settle(ids[1], 612001), false)
assert.equal(await reserve(ids[8]), 'reserved')
assert.equal(await reserve(randomUUID(), null), 'invalid')
assert.equal(await reserve(randomUUID(), 0), 'invalid')
const committed = Number((await db.query('select committed_micros from public.threadline_ai_budget_months')).rows[0].committed_micros)
assert.equal(committed, 4896400)
// Rollover fixture: preserve old unresolved holds; settle into both months.
await db.exec(`reset role;
  insert into public.threadline_ai_budget_months values ('2020-01-01', 0);
  update public.threadline_ai_budget_months set committed_micros = 4284000 where month = '2020-01-01';
  update public.threadline_ai_spend_reservations set month = '2020-01-01' where settled_micros is null and id <> '${ids[8]}';
  update public.threadline_ai_budget_months set committed_micros = 612400 where month <> '2020-01-01';
  set role service_role;`)
assert.equal(await reserve(randomUUID()), 'exhausted')
assert.equal(await settle(ids[1], 100), true)
assert.equal(await reserve(randomUUID()), 'reserved')
await db.exec('reset role; set role authenticated;')
await assert.rejects(reserve(randomUUID()), /permission denied/)
await assert.rejects(db.query('select * from public.threadline_ai_budget_months'), /permission denied/)
await db.exec('reset role; set role anon;')
await assert.rejects(settle(ids[2], 0), /permission denied/)
await db.exec('reset role;')
await assert.rejects(db.exec('update public.threadline_ai_budget_policy set monthly_limit_micros = 5000001'), /check constraint/)
await db.close()
console.log('PASS: SQL cap, duplicate reserve/settlement, invalid amounts, rollover holds, privilege isolation. Multi-connection lock contention still requires hosted staging verification.')
