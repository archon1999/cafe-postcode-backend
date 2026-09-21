# Service fee formulas — implementation contract

Status: implemented across backend, Admin, POS and Local Agent. Automated checks,
Admin browser authoring, and live POS disconnected payment/reconnect pass. The
simplified three-mode settings and receipt labels pass automated checks. The
latest Local Agent binary also passed live receipt/error/recovery/replay checks.
The Lumen first-hour template and `add_minutes` extension pass shared backend/Go
tests and a live local v3 Agent offline payment/reconnect check. PostgreSQL
migration reversal and replay were rehearsed. Production rollout is tracked in
`service-fee-production-readiness.md` and `service-fee-rollout.md`; a signed
production Agent release and fleet updates are still required.

## Required end state

- Specialist can write and save a technical expression or `let` / `return` program.
- Templates, visual constructor and AI produce the same editable formula definition.
- Restaurant, hall and table assignments retain additive behavior.
- Percentage, proportional time, first-hour minimum, each-started-hour and scheduled
  rates work, including crossing midnight and tariff boundaries.
- Definitions are versioned and frozen in session/order snapshots. Existing paid
  orders and open sessions are not retroactively repriced by editing a tariff.
- Online backend and offline Local Agent calculate the same result; POS displays
  and pays the authoritative quote. Reconnect replay preserves the frozen result.
- Preview, source diagnostics, parameters and calculation explanations are available.
- Settings expose None / Percentage / Formula. Percentage remains a native numeric
  setting. Current hourly settings migrate to equivalent formulas, preserving
  money and duration rounding; historical order/session snapshots remain intact.
- Percentage receipts show the rate. Formula receipts show only `Xizmat haqi`
  and the amount, without the formula name, source or rate.

## Language version 1

Programs contain zero or more `let name = expression;` statements and a final
expression, optionally prefixed by `return` and followed by `;`. `//` comments,
decimal literals, double-quoted strings, booleans, arithmetic, comparisons and
short-circuit `&&`, `||`, `!` are supported. There are no loops, assignments,
imports, property access beyond named context variables, network or file access.

Context: `subtotal` (UZS before service fee), `guest_count`, `duration_minutes`
(actual elapsed minutes, fractional), `session.started_at` / `started_at`, and
`calculation.at` / `calculated_at`. Numeric custom parameters cannot shadow context.

Functions: `min`, `max`, `abs`, `floor(value[, step])`, `ceil(value[, step])`,
`round(value[, step[, mode]])`, `round_money` (alias), lazy `if(condition, a, b)`,
`minutes_in([start, end,] "HH:MM", "HH:MM")` and
`time_in(timestamp, "HH:MM", "HH:MM")`, and
`add_minutes(timestamp, integer_minutes)` (actual elapsed UTC minutes, bounded to
±366 days; resulting UTC year must be 1970–9998). A time-valued binding may hold
the end of the first hour. Keep later `minutes_in` windows inside a lazy `if` for
short sessions, since a window whose start is later than end is invalid.

Windows repeat daily in the definition's IANA timezone (default Asia/Tashkent),
include their start and exclude their end. Reversed clock bounds cross midnight.
Equal bounds are rejected. `minutes_in` sums actual UTC elapsed overlaps over all
covered dates. It applies no minimum charge and no rounding itself. A minimum must
be applied deliberately once, outside the sum, according to the business rule.
Repeated DST wall times select their first occurrence. Skipped wall times use
the offset before the transition, matching Python zoneinfo `fold=0`.

Numbers use bounded exact rational arithmetic; no binary-float money calculation.
Remainder truncates the quotient toward zero. Rounding modes: `half_up` (default,
ties away from zero), `half_down` (ties toward zero), `floor`, `ceil`. Final money
must be nonnegative and at most 2147483647 UZS, rounded once to whole UZS half-up.
Per-component rounding happens before the existing additive total.

Source is compiled to versioned JSON operation arrays. The backend compiles source
itself and never trusts a submitted AST. Numeric parameters are decimal strings.
Definition revision is SHA-256 of canonical version/name/source/parameters/timezone.
Runtime rejects invalid expressions and never silently substitutes a zero fee.

## Authoring and assignment

Admin route: `/restaurant-admin/restaurant-management/service-fees` under My
Restaurant settings. The main form exposes None / Percentage / Formula; the
formula option accepts technical source directly, with no AI dependency. Advanced
tools are collapsed by default. Ten templates, the constructor (hourly/scheduled,
optional percentage addition and rounding), and AI produce editable formulas.
Preview shows the amount and intermediate `let` values. Changing the
formula, parameters or test context invalidates the previous preview. Saving
an advanced reusable policy requires a current successful preview in the UI.
Direct settings compile on save. The backend always compiles and
validates the submitted source; a sample preview is not a proof for every input.

Assign a saved active policy to a restaurant, hall/room or table. These components
remain additive. Each assignment copies the policy version. Editing or disabling
a policy does not rewrite existing assignments; explicitly reassign to adopt an
updated version. Session opening snapshots the applicable definitions and guest
count. The first successful payment freezes formula time. Existing empty fee
snapshots stay empty even if fees are enabled later.

Formula result errors block payment and prechecks, including cashier overrides.
Item edits remain valid so a later correction can recover. Order/list responses
return `service_fee_error` and null payable totals while invalid; recalculation
retains the last confirmed stored total instead of inventing a zero fee. This
also lets offline intermediate edits replay before their later corrections.
Custom time-dependent quotes
have a 30-second acceptance window and are evaluated at the quoted timestamp;
expired/changed quotes return the existing stale-quote response. Trusted offline
replay uses the saved freeze timestamp. Percentage uses the established native
calculation in Python and Go. Historic hourly components keep their established
calculation, first-hour minimum, five-minute steps and thousand-sum half-down
rounding. New time-based fees use formulas.

POS displays authoritative custom amounts from the backend/agent. While item
changes are pending it retains confirmed totals and shows a recalculation notice;
it does not execute custom formula source in JavaScript.

## Current authoring API

Under `/api/v1/admin/restaurants/service-fees/`:

- `GET catalog/`: templates, variables and function signatures.
- `POST preview/`: `{definition, context}` returns a validated definition, exact
  result, rounded amount and intermediate bindings, or position-aware diagnostics.
- `GET/POST policies/`: list/create within the selected restaurant.
- `GET/PATCH policies/<uuid>/`: read/update in the same restaurant scope. PATCH
  requires `expected_revision`; old editor state cannot overwrite a changed policy.
- `GET assignments/`: current restaurant/hall/table fee settings.
- `POST assignments/`: `{scope, target_id, mode, percent?, formula?}`. Mode is
  `none`, `percentage` or `formula`; percentage requires a numeric rate and formula
  requires a definition. A saved `policy_id` and `expected_revision` may be used
  instead of a direct definition. Policies must belong to the restaurant, be
  active and match the expected revision. The older policy-only request remains
  supported; a null policy disables the target's fee.
- `POST ai-draft/`: `{text, timezone}` returns `{definition, explanation, questions}`.
  Ambiguous requirements return questions without a placeholder zero-fee formula.
  Provider output uses a strict JSON schema and passes through the DSL compiler.
  It is never saved or assigned automatically. Uses the existing inventory AI
  configuration on the server; 6 requests/minute per user, no secrets in the UI.

These endpoints deliberately use plain JSON instead of the global camel-case
parser/renderer, because parameter identifiers (`dayRate` versus `day_rate`) are
case-sensitive code. The frontend repository must preserve the definition verbatim.
Read endpoints use `restaurant_settings.view`; mutations/preview/AI use
`restaurant_settings.update`. No order/restaurant billing configuration is changed
by previewing or storing a policy.

## Verified development checks

`python -m unittest common.tests.test_service_fee_formulas` exercises the language
and 53 manually specified conformance cases. Export the same programs for Go with
`python scripts/export_service_fee_fixtures.py ../local-agent/internal/servicefees/testdata/conformance.json`.
Then run `go test ./internal/servicefees` in local-agent. Django API tests live in
`apps.restaurants.tests.test_service_fee_formula_api`; use an explicitly isolated
local SQLite test database when running them.

Additional verification on 2026-09-21:

- 54 focused Django language/configuration/authoring/AI/order tests passed.
- Two additional wire-contract tests passed: configuration/bootstrap responses
  retain restaurant/hall/table formula definitions, case-sensitive parameters,
  compiled programs and captured guest counts; a hall-constructor layout edit
  preserves both hall and table formulas through a real JSON GET/PUT round trip.
- Signed Local Agent HTTP payment projection test confirms a five-minute-delayed
  formula payment retains its offline time and an identical replay creates no
  second payment (`test_formula_payment_replay_preserves_offline_freeze_and_is_idempotent`).
- `go test ./internal/servicefees ./cmd/local-agent -count=1` passed, including
  conformance, offline custom amounts, frozen snapshots, errors and legacy rounding.
- Admin editor race/revision tests: 5 passed. Existing Admin settings/routes/floor
  focused tests: 28 passed. POS payment/builder/presentation focused suite: 90
  passed, followed by 19 fee/optimistic tests including two additional cases.
- Admin and POS TypeScript checks and production builds passed. Changed frontend
  files passed ESLint. Builds emit the existing large-chunk advisory.
- Chrome on isolated SQLite `var/formula-ui.sqlite3`: directly entered a `let` /
  `return` scheduled program, previewed 17:30–18:30 as day=30, night=30 and 90000
  UZS, saved and assigned it. Unknown variable diagnostics include character
  position and disable save. AI is not configured locally; live provider calls
  were not exercised. Mocked provider tests cover schema, ambiguity and rejection.
- Chrome `http://localhost:4300/` reaches the existing paired restaurant PIN screen.
  No employee PIN was entered. Default local SQLite migrations were applied after
  a SQLite backup in `var/formula-before-migrations-20260921-202801.sqlite3`.
- Three broader-suite failures (table number strings versus integers and receipt
  VAT precision) were reproduced on clean baseline commit `52692ae`; they are
  unrelated to this change and were not modified.

Live runtime rechecked on 2026-09-21 at 15:54 UTC: the newly built
`local-agent/var/formula-local-agent.exe` is running with the separate Local Agent
Local config on port 18183 against backend `127.0.0.1:8000`. Its `/health` responds
successfully; the matching backend Device is ACTIVE and the LocalAgent row is
online with a fresh heartbeat. Existing Daphne (8000), Admin (4200), and POS (4300)
processes were reused. Chrome at `http://localhost:4300/` reaches the paired
restaurant PIN screen. No re-pairing or staff changes were needed.

Live offline/reconnect check passed after the user signed into the existing POS
session. A dedicated local `Formula offline QA` hall/table was created without
changing the restaurant's existing 10% fee. With Daphne stopped and port 8000
confirmed unavailable, the POS opened a four-guest table session, created and
submitted a 10000 UZS order, opened a local cash shift with zero starting cash,
and completed a non-fiscal cash payment through the Agent on port 18183.

The test table used a technical formula with `time_in(session.started_at, ...)`,
case-sensitive day/night parameters, `floor(duration_minutes)`, a 5% subtotal
component, and captured guest count. After two full minutes the table fee was
5900 UZS, restaurant fee 1000 UZS, and total 16900 UZS. The Agent queued the
payment with the original quote and freeze timestamp `2026-09-21T16:01:09.4376645Z`.
After restarting Daphne against the same local SQLite database, all seven queued
operations succeeded. Order `e98e86b9-0cfa-491c-b7d1-b634e8b220e2` and its session
were closed, with exactly one successful payment of 16900 UZS. The backend's
formula fee remained 6900 UZS when evaluated five hours later. The POS showed one
matching receipt and zero pending synchronization operations. No fiscal payment
or live provider transaction was requested.

The second live check used `var/formula-local-agent-v2.exe` on port 18183 and a
deliberately invalid branch, `if(subtotal >= 20000, 1 / 0, subtotal / 10)`. With
backend 8000 stopped, increasing the subtotal from 10000 to 20000 showed the
explicit division-by-zero error and disabled precheck/save. Reducing it to 10000
restored the 12000 total (1000 native restaurant percentage + 1000 formula fee).
Both cached precheck and ordinary payment documents contained the native rate
label and `Xizmat haqi` formula label, with an empty formula rate label.

This test exposed a reconnect bug: the backend rejected the intermediate invalid
item edit, preventing the later correction from replaying. The backend now accepts
editable invalid states while rejecting payment/printing. A regression test covers
create/read/cashier override/payment rejection/precheck rejection/recovery. After
the fix and an explicit retry of only the failed QA operation, all ten operations
succeeded. Order `0f6c1bb5-d7db-48cd-8655-e8b379bacdb2` and its session are closed,
with exactly one successful payment of 12000 UZS.

The dedicated QA cash shift was closed with 28900 UZS from the two local test
payments. The QA table/hall/zone were deactivated, their history retained, and the
deliberately invalid table configuration restored to the valid scheduled formula.
Existing restaurant settings, staff, and the other cashier's shift were preserved.
Daphne 8000 was restarted for the fix; Admin 4200 and POS 4300 were reused. No
production deployment, staff deactivation, or real fiscal transaction occurred.

Final additional checks: 54 simplified-mode backend tests, 21 printing tests,
13 recovery/print-document tests, 30 Admin focused tests plus 7 serialization
tests, 47 POS focused tests, Go formula/agent tests, frontend type checks/lint/builds,
Django system checks and migration-drift checks passed. The broader payment suite
retains its two known baseline table-number/VAT failures; the new recovery test
passes. AI provider calls remain mocked because the local provider is unconfigured.
