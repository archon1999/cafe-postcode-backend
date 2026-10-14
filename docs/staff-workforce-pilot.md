# Staff workforce pilot

The staff PWA lives in the sibling `staff-frontend` project. Its APIs are in
`apps.workforce`, `apps.payroll`, and `apps.users.api.staff`. There is no bank
or tax integration: a payout is a dated manual ledger entry only.

## Release preparation

1. Back up the database, then apply the `users`, `workforce`, and `payroll`
   migrations. `users.0006` records a per-restaurant count and snapshots of
   any nonempty legacy `EmployeeProfile` salary fields in
   `LegacyFieldMigrationAudit` before deleting those columns. Restrict access
   to that audit table because it contains old compensation values. It is not
   imported into the new payroll ledger.
2. Deploy the PWA on an HTTPS staff origin. Route `/api/v1/staff/` on that
   origin to the backend and serve PWA files for other paths. Configure
   `STAFF_PWA_PUBLIC_ORIGIN` for invitation links and
   `STAFF_AUTH_ALLOWED_ORIGINS` to that exact origin. Keep the refresh cookie
   Secure, HttpOnly, and SameSite Strict; do not cache staff API responses at
   the reverse proxy. The service worker caches static assets only.
3. Grant `workforce.view`, `workforce.schedule`, and `workforce.approve` to
   managers as needed. Only the branch administrator receives
   `workforce.config` by default. Financial access is separate:
   `staff.payroll.view`, `staff.payroll.manage`, and `staff.payroll.payout`.
   Ordinary staff receive only their own workforce and locked payroll views.
4. Use the existing admin employee detail action to issue an expiring,
   single-use staff invitation. Share its link privately. POS PINs do not
   create staff sessions. A disabled employee or removed restaurant access
   invalidates staff access.

## Enable one branch

1. With a branch administrator's staff session, set the restaurant's geofence
   center, radius (150 m by default), and `workforceEnabled=true` in the
   Jamoa screen. Other branches stay disabled. A punch outside the radius or
   without GPS remains visible and requires manager review; it is not dropped.
2. Add effective-dated hourly, daily, or monthly rates. Add a branch default
   or role-specific POS KPI rule only if POS sales KPI is wanted.
3. Create weekly schedule templates or shifts, publish them, and invite the
   pilot employees. The PWA can queue an offline punch; its eventual server
   import is provisional and must be reviewed.
4. Resolve correction requests and approve timesheets. The payroll module
   uses approved minutes/shifts only. Monthly base pay remains fixed until an
   explicit approved adjustment changes it. Review POS KPI after payments and
   refunds settle. A changed KPI snapshot blocks the first payroll lock until
   it is approved again.
5. Build and lock a payroll period, then record actual cash or external
   transfer payments with date, amount, and note. The app never sends money.
   Void mistaken entries with a reason. Changes after a lock require a new
   approved correction and locked calculation version.

Run this branch alongside the current manual payroll for two full periods.
Compare each employee's approved minutes/shifts, base, KPI, adjustments,
paid amount, and balance; investigate discrepancies before enabling more
branches. Keep `workforceEnabled=false` elsewhere during the pilot.

The optional Hikvision connector has its own setup in the sibling
`local-agent/docs/hikvision-attendance-pilot.md`. Its ISAPI event shape must
be checked against the physical DS-K1A340FWX firmware before enabling it.
Review penalty rules and any selfie/biometric handling against applicable
Uzbek employment and personal-data requirements before production release.

## Local release verification, 14 October 2026

The full PostgreSQL release suite passed 475 tests across local agents, user
authentication, workforce, payroll, integrations, and catalog. It includes
refresh-family concurrency, tenant isolation, replay idempotency, overnight
attendance, payroll locking and manual payouts. Migration drift checks and
changed-code lint passed. Production deployment now requires the sync,
Staff, and fiscal tests in the existing PostgreSQL CI gate.

Refresh rotation locks only the token and family rows, not joined user and
restaurant rows. Separate families can rotate concurrently; concurrent reuse
of one cookie still permits only one rotation without revoking the family.

The sibling Staff app passed its build, typecheck, five Tashkent calendar
boundary tests, and a desktop/mobile login rendering check. Admin passed
469 tests and its production build. This verification made local commits;
it did not deploy or repeat the historical production checks in the Staff
README. Docker image builds and physical-device acceptance remain release
checks, since this workstation has no Docker CLI or connected test printer.
