# Service fee production readiness — 2026-09-21

Current status: the release candidate passed local Agent v3 disconnected payment,
receipt and reconnect checks, and PostgreSQL forward/reverse/forward migration
rehearsal. The user requires updating all Agents; compatibility with old Agents
is intentionally not part of this release. Production rollout and Lumen tariff
activation have not been performed. See `service-fee-rollout.md` for release order
and rollback constraints. The original audit and follow-up evidence follow below.

## Production facts

Read from the production PostgreSQL database at 21:53 Asia/Tashkent in an explicit
read-only transaction with a 15-second statement timeout. Restaurant, hall and
table settings were all inspected, including inactive/disabled hourly settings.

| Branch | Scope | Configured rate | Active/enabled |
| --- | --- | --- | --- |
| "LUMEN" LOUNGE BAR | Hall `Kabina` | 100000 UZS/hour | Yes; branch, zone and hall active |
| OTAMAKON | Table `1-stol`, number `1`, hall `KABINA` | 10 UZS/hour | Yes; branch, zone, hall and table active |

There are no restaurant-level hourly settings and no other hourly hall/table
settings. OTAMAKON contradicts the expectation that only Lumen uses hourly fees.
Its 10 UZS rate is recorded literally, not interpreted as 10 percent or 10000 UZS.
It was not changed. Lumen has one non-closed session with an hourly snapshot.

Lumen's Agent reports version 2.2.3, online. OTAMAKON's reports 2.2.5, online.
The fleet also includes older Agent releases and offline branches. Formula
migrations restaurants/0030–0032, floor/0009 and printing/0015 are not applied.

## Percentage and hourly parity

The production Python percentage and legacy hourly calculation functions were
read with `inspect.getsource`; their parsed ASTs match the current local functions
exactly. Percentage remains a native calculation and migration 0032 selects only
`service_fee_mode='hourly'` rows. It does not rewrite percentage settings.

The two production hourly rates (100000 and 10) were tested against the proposed
formula at 17 elapsed-time boundaries each: zero, partial minutes, 30 minutes,
the first-hour boundary, five-minute boundaries, 90 minutes, two hours and 24 hours.
All 34 results match the existing first-hour minimum, five-minute flooring and
nearest-thousand half-down rounding. Existing session/order snapshots are retained.

## Original release blockers (superseded by the follow-up below)

1. **Agent compatibility before hourly migration.** The released Agent calculation
   path does not support formula components. With `mode='formula'` and zero
   percentage, its legacy normalizer drops the component. Migration 0032 changes
   both hourly settings automatically; new sessions on an old Agent can therefore
   omit the hourly fee. Roll out and verify the formula-capable Agent before
   converting settings, or defer conversion behind a verified capability gate.

2. **Percentage receipt compatibility.** Printing migration 0015 changes published
   rows to `totals.*ServiceFeeLabel`. Older Agents produce `*ServiceFeeRateLabel`
   and do not populate the new full-label fields in offline documents. Even a
   percentage-only branch can lose its service-fee caption during a mixed-version
   rollout. Keep templates backward compatible or verify all relevant Agents are
   updated before publishing these rows; offline branches must be accounted for.

3. **Data rollback.** Migration 0032 uses a no-op reverse. Reverting application
   code or migration state alone does not restore migrated hourly settings.
   A release needs an explicit data rollback procedure or reversible conversion,
   plus a PostgreSQL migration rehearsal. Prior migration tests used local SQLite.

The successful local end-to-end checks do not remove these mixed-version rollout
risks. The AI authoring path has mocked provider coverage, but live provider calls
have not been verified for this change.

Raw scoped audit data is in ignored local file
`var/service-fee-production-audit-20260921.json`; it contains rates and Agent
versions, not credentials. No customer orders or production settings were edited.

## Authorized follow-up — 22:51 Asia/Tashkent

The user identified OTAMAKON's 10 UZS/hour table fee as test configuration and
explicitly requested its removal. Only table
`afad9fce-82e5-4bdb-9430-0d65d044d254` was changed, inside a locked transaction:
fee disabled, mode reset to percentage, percentage/hourly rate both zero. There
were no non-closed sessions on this table. Configuration invalidation was sent;
a separate read-only query verified the committed settings. Original orders and
history were not edited. The before/after receipt is retained locally in
`var/otamakon-test-fee-removal-20260921.json`.

Only Lumen's `Kabina` hall now has hourly mode anywhere in production.
The user specified day rate 50000 UZS/hour (09:00 inclusive–18:00 exclusive), night
rate 100000 (18:00 inclusive–09:00 exclusive), splitting elapsed time across the
windows, with a one-hour minimum. The final clarification fixes the first hour at
the arrival tariff, even when that hour crosses a shift boundary. Only elapsed
time after the first 60 minutes is split across the day/night windows.
Earlier pure-window examples (17:30–18:30 = 75000) are superseded by this rule.

The local `scheduled_first_hour` template implements the rule with 50000/100000
parameters and `add_minutes(session.started_at, 60)`. For example, 17:45–18:15
and 17:45–18:45 both cost 50000; 17:45–19:15 costs 100000. Arrival at exactly
18:00 uses 100000. Arrival at 08:30 uses 100000 for the first hour, then 50000/hour
after 09:30. The minimum is applied only once. Subsequent time is prorated at
actual elapsed fractional minutes, with final whole-UZS half-up rounding, not
the legacy five-minute/thousand-UZS rounding.

Thirteen Lumen boundary cases and seven timestamp-offset cases were added to the
shared backend/Agent conformance suite, including midnight, multiple days, zero
elapsed time, fractional minutes, DST and invalid offsets. The technical formula
is in `docs/lumen-service-fee-formula.md`.

Validation after the clarification: all 53 shared conformance cases passed in
Python and Go; 38 focused Django language/catalog/preview/assignment/AI tests
passed on an isolated SQLite test database. The Go formula/service-fee/receipt
checks also passed. AI tests use mocked provider responses.

The production Lumen setting remains the original flat 100000 hourly fee.
At that stage, the running local v2 Agent predated `add_minutes`; source test
success did not update a running binary. The follow-up below replaces that state.

## Final local verification — 23:15 Asia/Tashkent

The user replaced local Agent v2 with `var/formula-local-agent-v3.exe` (PID 11988,
port 18183), including `add_minutes`. Admin 4200 and POS 4300 were reused. Daphne
8000 was restarted with current source, deliberately stopped for offline testing,
and brought back for replay. No production Agent/config was used for this test.

- The first-hour Lumen template was assigned only to the existing local QA table.
  A new session and mineral-water order were created in the paired Chrome POS
  while port 8000 was not listening. The night first-hour fee was 100000,
  restaurant 10% was 1000, item subtotal 10000, total 111000.
- Precheck, submit and plain cash receipt succeeded offline. Cached document
  snapshots contain `Restoran xizmati (10%)` and `Xizmat haqi` with 100000; the
  formula's rate label is empty. Physical paper output was not inspected.
- Reconnect applied all eight mutations successfully. Order
  `2c30925b-7de6-422c-8f26-3f8957be1e89` and session
  `ac998029-e053-44e0-9373-1aaa0e4ed466` are closed; exactly one payment
  `abbb210a-d5f3-0d9f-1a38-13028577c5ac` exists for 111000. Computing five hours
  later still returns frozen combined fees of 101000. Agent queues are empty.
- The temporary QA floor was deactivated and QA cash shift
  `8a0f0b42-8d89-456e-a666-a9897353234d` closed with 111000 cash. Original orders,
  original open shift and all test history were retained; no users deactivated.
- An isolated PostgreSQL 17.11 cluster on loopback port 55433 passed 31 focused
  migration/authoring/order/receipt tests, including a real migration graph
  forward/reverse/forward test. No production database was used or copied.
- Migration 0032 now restores unchanged legacy hourly configurations and refuses
  custom/modified definitions or formula billing history. Printing 0015 restores
  the original published version without deleting version history; later edits
  cause a guarded failure. PostgreSQL checks are included in the deploy workflow.
- All Agent Go packages passed. Five final PostgreSQL rollback/rehearsal tests
  passed after adding the billing-history safeguard.
- A separate PostgreSQL test passed for refusal to overwrite an edited receipt
  layout, verifying no other template changes before failure. The temporary
  PostgreSQL instance was stopped after checks; the normal local stack remains up.

Raw local test logs: `var/formula-postgres-tests.log`,
`var/formula-postgres-rollback-tests.log`; Agent suite log:
`../local-agent/var/formula-release-go-tests.log`.
