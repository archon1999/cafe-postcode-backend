# Submission preparation — 2026-09-16

## Deployed and verified

- Code: `c658c120db6b35a3fc89ad64ef37dd1ada33b886`, isolated `mcp-submission` branch based on deployed `ce8e774`; excludes unrelated inventory commits.
- Image: `sha256:93d51a59d95ae3273b0a2c31aded33430563111e9771610a0a02a994daf5cb3d`.
- CI: https://github.com/archon1999/cafe-postcode-backend/actions/runs/35119253907 — 66 PostgreSQL tests and 31 final-image tests passed; HIGH/CRITICAL scan passed; signed artifact verified against the exact submission branch identity and revision before loading.
- Local: 31 MCP tests passed. Synthetic dataset totals, role permissions, foreign-tenant denial and duplicate-seed refusal covered.
- Runtime database role isolation and migration check passed. Restricted login/session/CSRF consent/PKCE exchange passed within rollback.
- Public HTTPS smoke passed for two existing restaurant accounts: 11 tools, eight report types, chart, foreign-tenant denial and revocation. Temporary smoke credentials removed.
- Public widget resource v4 advertises the unique MCP origin and closed network/resource allowlists in both standard and compatibility metadata.
- Public TLS, health, discovery, login/security headers and brand asset passed. Internal readiness and unrelated API routes remain inaccessible publicly.
- Existing 512px brand logo and listing copy ready. Five positive and three negative reviewer cases written with exact synthetic expected values.
- Domain challenge handler implemented; returns 404 until the real portal token is configured. This is not a completed domain verification.

## Still pending; do not submit yet

1. Publisher identity, support contact, final public privacy/terms, availability and attestations: explicitly deferred by owner. No fabricated policy/contact has been published.
2. Live synthetic review account: provisioning command is ready and tested, but not executed on production. The backup reserve check failed with approximately 7.5 GiB free, so no review business records were written. Resolve storage capacity, take a verified backup, rehearse and commit the reserved synthetic dataset, then test external login and provide credentials privately in the portal.
3. ChatGPT Refresh and visual acceptance of v4 with CSP enforcement: browser control timed out repeatedly. Backend delivery is verified, host rendering is still pending. No claim that the prior developer-mode CSP warning has disappeared.
4. Portal: final logo upload, exact OAuth callback/client registration, issued domain token, Scan Tools, reviewer tests and submission remain pending. Existing development connection is unchanged.

Pilot detail link verified in the owner's signed-in account:
https://chatgpt.com/plugins/plugin_asdk_app_6aaa9ad7ba008191b0c995c3d1e4470e

This appears under Personal plugins. Cross-account installation via this link was not verified; the public MCP endpoint is not itself a one-click install link.

Operational evidence is under `/home/postcode/mcp/evidence/`; local command logs are in the original backend's ignored `var/mcp-submission-*.log`. Main POS containers were not deployed by this work. No inventory tool was added.
