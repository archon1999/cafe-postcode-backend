# Cafe Postcode — ChatGPT analytics MCP

Read-only business reports over authenticated Streamable HTTP. The dedicated
ASGI application exposes `/mcp`, OAuth and connection management; it does not
mount the POS, admin or general API routes. Business records are never modified
by tools. OAuth records and short-lived report snapshots are stored in the DB.

## Available tools

| Tool | Result |
| --- | --- |
| `list_branches` | Current permitted branches intersected with original consent |
| `get_sales_summary` | Gross receipts, refunds, net receipts, closed orders, average check; optional previous-period comparison |
| `get_sales_timeseries` | Daily points, or hourly points for one day; empty buckets included |
| `get_top_products` | Closed-order products by line revenue or quantity |
| `compare_branches` | Same-period branch rows, with separate currency on each row |
| `render_sales_chart` | Interactive chart/table from an authorized saved timeseries |
| `get_expenses` | Posted cash expenses by category; requires `expenses.view` |
| `get_staff_performance` | Closed-order item revenue/quantity by staff; requires `reports.view` |
| `get_table_performance` | Closed dine-in orders by primary table and hall |
| `get_payment_breakdown` | Successful payments minus refunds by payment method |
| `get_cash_shifts` | Shift totals for shifts opened in the selected period |

Inventory is deliberately deferred. Single-restaurant presentation contains no
branch list, count, selector or comparison; multiple restaurants retain these.
Staff totals describe attributed sales, not employee quality or cashier receipts.
Table totals do not allocate refunds; cash-shift totals cover the whole shift,
not just the selected date interval. Each result includes its metric definition.

All dates use Asia/Tashkent. `last_7_days` includes today plus six previous days;
`previous_week` means the previous Monday–Sunday. Date ranges are inclusive in
the API and converted to half-open DB intervals. Today stops at `generated_at`.
Amounts use the existing database currency units. Net receipts subtract
succeeded refunds by **refund date**, and are not profit. Product line revenue
does not allocate refunds; quantity ranking requires a single unit. Identically
named products across branches are grouped by name/category/type/unit, not a
global SKU. Offline transactions not synchronized centrally are absent; there
is currently no trustworthy sync watermark, so freshness explicitly says unknown.

## Local startup

Run from `backend`. Set `SQLITE_PATH` to a verified disposable local DB when
testing with synthetic data. These migrations also install Django OAuth Toolkit.

```powershell
poetry install
poetry run python manage.py migrate
$env:DJANGO_SETTINGS_MODULE = 'core.settings.mcp'
$env:DJANGO_SETTINGS_CLASS = 'MCPSettings'
$env:MCP_PUBLIC_ORIGIN = 'http://127.0.0.1:8765'
$env:ALLOWED_HOSTS = '127.0.0.1,localhost'
poetry run uvicorn core.mcp_asgi:application --host 127.0.0.1 --port 8765 --no-access-log
```

`/healthz` is a process liveness endpoint, not a database readiness check.
Unauthenticated `/mcp` returns 401 with protected-resource discovery metadata.
The core POS stack continues to use its normal Daphne entry point; this separate
process needs the MCP SDK's ASGI lifespan.

## Connect ChatGPT

1. Serve this process through HTTPS with a stable public domain. Set
   `MCP_PUBLIC_ORIGIN` to that origin without `/mcp`, `ALLOWED_HOSTS` to its host,
   and `CSRF_TRUSTED_ORIGINS` to the HTTPS origin. Enable secure session/CSRF
   cookies. Restart after changing the public origin: it is also the token audience.
2. In ChatGPT's developer app creation form, enter `https://your-host/mcp`,
   choose OAuth and a predefined client. Copy the **exact callback URL shown by
   ChatGPT**; do not guess it or use a wildcard.
3. Register the client against the same DB:

   ```powershell
   poetry run python manage.py register_mcp_client --name 'Cafe Postcode ChatGPT' --redirect-uri 'EXACT_HTTPS_CALLBACK_FROM_CHATGPT'
   ```

   Copy the one-time client secret into ChatGPT. Select `client_secret_post`
   and scope `analytics:read`. Keep credentials out of source control/logs.
4. Connect with an active restaurant account having `dashboard.view`, an enabled
   restaurant entitlement and branch access. A global superuser cannot connect.
   Confirm restaurant access on the consent screen. Existing account MFA applies;
   accounts required to enroll must first set up Authenticator in Admin.
5. Ask “Bugungi statistika”, “Oxirgi 7 kunlik grafik”, or “Top 10 mahsulot”.
   `/oauth/connections/` lets the restaurant user revoke their own connections.

There is no dynamic client registration, OIDC or public unauthenticated tool
access. OAuth authorization code + mandatory S256 PKCE binds the exact MCP
resource. Tokens and client secrets are hashed by Django OAuth Toolkit. Access
tokens last one hour, refresh tokens rotate with replay protection, and consent
expires after 30 days by default. Adding a branch requires renewed consent;
removing permissions or revoking a connection affects subsequent tool and
snapshot reads immediately. Already delivered ChatGPT messages cannot be recalled.

## Production and capacity

Use the existing production environment requirements (`DJANGO_PRODUCTION=1`,
PostgreSQL, strong secret, distinct migration/runtime roles, Redis, TLS). Run
migrations using the migration role before starting MCP workers. Runtime needs
read access to business tables and normal writes to OAuth/session/analytics
tables. Keep OAuth and snapshots on the authoritative database; a lagging read
replica must not decide revocation or consent.

```text
poetry run uvicorn core.mcp_asgi:application --host 127.0.0.1 --port 8765 --workers 2 --limit-concurrency 64 --no-access-log
```

Pin `DJANGO_SETTINGS_MODULE=core.settings.mcp` and
`DJANGO_SETTINGS_CLASS=MCPSettings` in the service environment. The transport
has no per-process MCP sessions, so workers do not need sticky routing. Snapshot
storage is shared. Redis is required for shared rate limits; development's local
memory cache only limits each process. ORM calls use independent connections;
the per-worker report semaphore bounds concurrent report execution. Configure
proxy request timeouts/body limits and PostgreSQL `statement_timeout` for the
dedicated runtime role according to measured load. Trust only the actual TLS
proxy's forwarded headers; do not expose the loopback server directly.

| Setting | Default |
| --- | --- |
| `MCP_CONNECTION_DAYS` | 30 |
| `MCP_REPORT_TTL_SECONDS` | 900 |
| `MCP_MAX_DAYS` | 90 |
| `MCP_RATE_PER_MINUTE` | 60 authenticated MCP requests per user |
| `MCP_MAX_CONCURRENT_REPORTS` | 8 per worker |

Request bodies are capped at 64 KiB. Reports accept at most 50 selected branches;
top products are capped at 50 rows. Sales series use three grouped queries and
branch comparison four, independent of branch count. Permission checks still
scale with the number of accessible branches. This MVP has not been load-tested
on production PostgreSQL volumes; measure query plans/latency before setting a
capacity target. Use summary tables later if volume justifies them, preserving
the report contract, authorization and refund-date semantics.

Schedule `poetry run python manage.py cleanup_mcp_reports` hourly. Run Django
OAuth Toolkit's `cleartokens` according to the desired token retention policy.
Audit logs contain tool, user/connection IDs, authorized branches, period,
duration and outcome, not bearer tokens or complete financial payloads. Avoid
logging OAuth callback query strings at the reverse proxy.

The chart is self-contained: no external scripts, assets or network requests.
ChatGPT developer mode rendered it successfully. Public marketplace submission
is a separate release step: assign/verify a widget domain and CSP against the
current submission requirements. The developer UI flags the missing unique
widget domain; this implementation has not been submitted to the marketplace.

## Add report domains

The boundaries are intentionally separate:

- `policy.py` resolves current user + consent + tenant scope, failing closed.
- `contracts.py` validates inputs and supplies the versioned result envelope.
- `reports/*.py` contains domain calculations using **only** `context.branches`.
- `registry.py` declares tool metadata, input model, permission and handler.
- `service.py` applies policy, period/currency rules and snapshot storage.
- `server.py` handles MCP transport, errors and audit logging; `oauth.py` handles
  OAuth independently of report domains.

For a new domain, create its input model (derive from `PeriodInput` when dated,
otherwise `BranchInput`), a handler `(context, params) -> dict`, and a module-level
`REPORTS` tuple of `ReportDefinition` values. Add the module to
`CoreSettings.MCP_REPORT_MODULES`. The tool catalog and dispatch update without
editing OAuth or the server. Specify the domain's existing RBAC permission and
entitlement, `metric_basis`, currency behavior, row limits and persistence.
Every ORM queryset must be scoped to `context.branches`; never accept a user ID,
raw SQL or arbitrary ORM filters from the model. Use aggregate staff results
without exposing unnecessary personal fields. Add a separate UI renderer only
when needed; its saved-report loader must recheck current authorization just as
`load_chart` does. If the envelope's meaning changes, version it.

New reports must prove other-tenant denial, permission/entitlement revocation,
correct period boundaries and canonical business totals. Tests should also cover
domain-specific failures such as units, cancelled orders or stock adjustments.

## Verification — 2026-09-16

```powershell
poetry run python manage.py test apps.analytics_mcp.tests --noinput
poetry run python manage.py test apps.dashboard.tests apps.reporting.tests --noinput
poetry run python manage.py makemigrations --check --dry-run
poetry run ruff check apps/analytics_mcp core/mcp_asgi.py core/settings/mcp.py --extend-select F401
```

MCP tests cover tenancy, consent, roles/entitlements, superusers, audience,
expiry, refunds, fractional units, midnight boundaries, currency, OAuth exchange,
PKCE, refresh/replay/revocation, CSRF, transport, widget resource, additional
report domains, MFA replay and asset/security headers. The release workflow runs
MCP plus existing dashboard/reporting tests on PostgreSQL, then MCP tests again
inside the final Alpine runtime image.

The real Chrome/ChatGPT OAuth flow and all main report tools were exercised
against a separate synthetic SQLite database. Only DEMO Chilonzor and DEMO
Yunusobod were returned; a third unrelated tenant was excluded. Expected and
observed values: today gross 2,251,000 UZS, refunds 20,000, net 2,231,000;
last seven days net 9,983,000; top products Osh 7,595,000, Salat 1,232,000,
Choy 1,176,000. The embedded chart and expandable data table rendered in ChatGPT.

[Verified ChatGPT conversation](https://chatgpt.com/c/6aaa79c2-7224-83ed-9401-0ffaa167ab9d)

The test used a temporary Cloudflare HTTPS tunnel and local synthetic data.
This does not constitute production deployment. The tunnel and local process
must remain running for new demo queries; stored chat results remain visible.
