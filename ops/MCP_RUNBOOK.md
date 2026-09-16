# Cafe Postcode MCP operations

The MCP service is a separate Compose project in `/home/postcode/mcp`, on the
existing `backend_default` network. It listens only on `127.0.0.1:18765`; host
Nginx exposes `https://mcp.cafe-postcode.uz/mcp` through Cloudflare. The normal POS
checkout and containers are independent. Do not run the general production
deployment workflow merely to update MCP.

## Release and checks

1. Push reviewed MCP changes to `mcp-production`. Require the **MCP release**
   workflow to pass tests and the HIGH/CRITICAL image scan before downloading its
   release artifact. A public Autobahn documentation example key has a narrowly
   matched secret-scanner exception; vulnerabilities are not blanket-ignored.
2. Verify `release.sigstore.json` against `SHA256SUMS` with Cosign. Require issuer
   `https://token.actions.githubusercontent.com` and exact certificate identity
   `https://github.com/archon1999/cafe-postcode-backend/.github/workflows/mcp-release.yml@refs/heads/mcp-production`.
   Check every SHA256SUMS entry, load the image, and verify the revision label and
   non-root user. Set `MCP_IMAGE` to its immutable image ID, never a moving tag.
3. Take and validate a PostgreSQL backup while holding the existing deployment
   lock. Rehearse restore and migrations on a separately named disposable DB.
   Inspect pending migrations; an MCP-only release must not silently apply
   unrelated pending POS migrations. Keep backups and restore evidence.
4. Run migrations with the database owner in a one-off container. Keep owner
   credentials out of the long-running service. Provision the dedicated role
   using `ops/provision-mcp-role.sql`, including SELECT on `django_site`, which
   Django's login view needs. Do not grant business-table writes.
5. Run `check_mcp_database_role` and `verify_mcp_reports --application-id ID
   --username RESTAURANT_ACCOUNT` using the runtime role. The latter rolls back
   its temporary OAuth and report records. Verify both reports and OAuth HTML
   with the restricted role before routing external traffic.
6. Start only the `mcp` service with `docker compose up -d --wait mcp`. Check
   loopback readiness, public discovery, unauthenticated MCP 401, login/assets
   200, public readiness 404, and safe OAuth headers. Exercise an authenticated
   scoped MCP call and revoke it. Never log bearer tokens or financial payloads.

The root-owned `.env` is mode 0600. It contains an independent Django secret,
dedicated PostgreSQL credentials, and the existing Admin MFA key configuration.
Do not rotate the MFA keys independently: they decrypt existing enrolled accounts.
The ChatGPT client uses its exact displayed callback URL and `client_secret_post`.
Restaurant credentials are entered at the Cafe Postcode origin, not ChatGPT.

## Current deployment and evidence

The deployed application revision is `ce8e774f2d029982f785684f3a77ed529ed2d896`.
Its immutable image is
`sha256:f88492777680f579a9b183de9eebc6ac9f57efc035bc3673d54204531896e5db`.
Release run `35106947156` passed 64 PostgreSQL tests, 29 runtime-image tests,
the HIGH/CRITICAL image scan, and signed-artifact verification on the host.
The login corrections preserve CSRF protection with `Referrer-Policy:
strict-origin`, skip profile synchronization on authentication metadata saves,
and verify legacy password hashes without requiring business-table writes.
Both application and Nginx must retain the compatible referrer policy; using
`no-referrer` makes native browser login form submissions send `Origin: null`.

NEW YORK and BOHRAM DIYOR passed authenticated HTTPS report, tenant-isolation,
chart-resource, and token-revocation checks on this release. NEW YORK also passed
restricted-role session, consent, and PKCE exchange preflight. The user then
confirmed successful real browser login; ChatGPT displayed today's statistics
and the seven-day `sales-chart-v3.html` widget without single-restaurant branch UI.
The v3 release removes routine offline/partial-day/profit disclaimers from
normal answers while retaining accounting metadata, uses system sans typography,
and removes the chart's cutoff, sync footer and duplicate border. New-chat
acceptance confirmed the concise answer and rendered widget (a first template
fetch failed transiently; the UI retry succeeded).
The MCP server advertises the existing Cafe Postcode logo through server icons.
The current ChatGPT developer app did not adopt it after refresh; its UI offered
name/description editing only, with no logo field. Do not claim the plugin card
icon has been updated. Logo publication remains a ChatGPT distribution step.
Host evidence is stored under `/home/postcode/mcp/evidence/`: signed-release
verification, backup checksums, restore result, migration plans, production
report checks, HTTPS smoke results, and deployed image ID. The disposable
rehearsal database was removed after success; both backups were retained.

Check the service:

```sh
cd /home/postcode/mcp
docker compose ps
docker compose exec -T mcp python manage.py check_mcp_database_role
docker compose logs --tail 100 mcp
systemctl status postcode-mcp-cleanup.timer
journalctl -u postcode-mcp-cleanup.service --since today
```

`/healthz/` checks process liveness. `/readyz/` checks PostgreSQL and Redis and is
intentionally blocked at the public proxy. Docker checks readiness every 30 s.
The hourly cleanup timer removes expired report snapshots and OAuth tokens.
Health checks and logs are configured; off-host alert delivery and sustained
capacity/load testing must be configured before claiming a broad rollout SLA.

## Rollback

For this first additive release, stop only the `postcode-mcp` service and restore
`/etc/nginx/conf.d/postcode-mcp.conf` to include the retained bootstrap config.
Run `nginx -t` before reloading. Disable the MCP cleanup timer if retiring the
service. Do not drop new tables or restore an old backup over live POS sales.
The original POS image was not changed. For later MCP updates, retain the previous
verified image ID and restore it in `.env`, then recreate only the MCP service.

## Remaining distribution steps

The production developer app is configured in ChatGPT. Each restaurant user must
sign in and approve its scope before ChatGPT can access that restaurant. Public
marketplace publication is separate: finalize the widget domain, review CSP,
privacy/support pages and OpenAI submission requirements before submitting.
The browser acceptance run used the account's existing developer-mode CSP
enforcement setting (disabled); repeat widget acceptance with enforcement enabled
before public distribution. The account-wide setting was not changed.
Inventory remains out of scope for this release.
