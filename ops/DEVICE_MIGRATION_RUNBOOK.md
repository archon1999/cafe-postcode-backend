# Device authentication production migration runbook

This runbook is an operational safety gate, not authorization to deploy. Do not
change production, push the `production` branch, or run any command below until
the system owner explicitly approves the rollout window.

## Safety guarantees and current limitation

The database changes in this release are backward-compatible with the currently
deployed application:

| Migration | Forward strategy | Rollback strategy |
| --- | --- | --- |
| `restaurants.0025` | Retire `auth_code` in Django state; retain the physical unique column as nullable | Reverse hook generates a unique code for every new restaurant before restoring `NOT NULL` |
| `kitchen.0008` / `0009` | Add the generalized device binding first; retire the TV auth hash in Django state and retain its physical column as nullable | Reverse hook restores missing restaurant codes and matching TV hashes |
| `local_agents.0006` | Remove the enrollment-token model from Django state only | The table and all rows remain physically available to the old release |
| `integrations.0013` | Add an encrypted shadow column, backfill it idempotently, retain the plaintext column as nullable, and point the new ORM at the encrypted column | Reverse hook decrypts every current row, including rows created after rollout, before the old column is made non-null |
| Device, MFA, Telegram, and session migrations | Add new nullable columns/tables/indexes | Old code ignores them; do not remove them during an emergency application rollback. MFA data is retained even though interactive Admin, Control, and Dashboard login is password-only in this release. |

No destructive database drop is part of this rollout. Physical cleanup must be
a later, separately approved contract release after the rollback window.

The current Compose topology has one `web` container. Its replacement is a
controlled restart, **not guaranteed zero-downtime**. The schema migration can
run while the old application serves traffic, but zero HTTP failures requires a
tested blue/green or multi-replica application rollout. Do not describe this
release as zero-downtime until that topology has been rehearsed.

## Hard go/no-go gates

All items below must be true before deployment:

1. Explicit system-owner approval for the exact UTC start time and release SHA.
2. A production-like PostgreSQL restore rehearsal has completed from a fresh
   verified backup. `pg_restore --list` alone is not a restore rehearsal.
   The same backup has an encrypted, checksum-verified, immutable off-host copy;
   a dump that exists only on the production disk is not a recovery plan.
3. Backend tests, migration contract tests, `makemigrations --check`, Ruff,
   `manage.py check --deploy`, and dependency audit are green for the release SHA.
4. All frontend and Local Agent release gates are green, and the Local Agent
   package/signature matches the published manifest.
5. At least three times the current PostgreSQL database size plus 5 GiB is free
   on the backup filesystem. The checked-in backup script enforces this before
   writing. Do not deploy when disk pressure is unresolved.
6. `.env.production` contains distinct owner, runtime, and monitoring database
   roles plus the valid integration Fernet key set. If existing MFA-encrypted
   rows may need rollback, retain their original dedicated MFA key set even
   while `ADMIN_MFA_REQUIRED=0`. Never reuse `SECRET_KEY`.
7. `DEVICE_LEGACY_MIGRATION_STARTED_AT` and
   `DEVICE_LEGACY_MIGRATION_DEADLINE` are explicit timezone-aware UTC values,
   the deadline is after the start, and their interval is no longer than 24
   hours. The planned start and end must both be staffed.
8. Integration/printer/payment configuration changes are frozen from the start
   of the migration until the new `web` health check passes. Old workers may
   read the retained plaintext column, but concurrent old-code writes could race
   the encrypted shadow backfill.
9. A human is available to verify representative live POS order, payment,
   printing, TV, Telegram, and admin flows immediately after the switch.
10. The protected GitHub production environment contains pull-only
    `GHCR_USERNAME`/`GHCR_TOKEN` credentials, and the release job produced the
    exact immutable image digest for the approved SHA.
11. A pinned, operator-managed Cosign binary is installed on the production
    host. The workflow's keyless signature identity and GitHub OIDC issuer must
    verify before the image is pulled; never bypass this check.
12. No secret or database dump is group/world-readable. Move the legacy
    `/home/postcode/credentials.txt` values into the approved secret store,
    verify consumers, then remove that plaintext file through a separately
    approved operation. Backup directories must be mode `0700`; dumps and
    checksums must be mode `0600`.
13. The host Nginx Cloudflare network list has been compared with Cloudflare's
    current published list. A direct-origin HTTPS request must be rejected while
    Cloudflare traffic and ACME validation still work. Restrict host ports 80/443
    to trusted edge ranges at the firewall as defense in depth where the ACME
    design permits it.
14. Root SSH keys and accepted source addresses have been reconciled to named
    owners, unrestricted or duplicated keys removed, and the pending kernel/
    package update plus controlled reboot has a separately approved window.

Any failed gate means **stop**. Do not use `--fake`, manually edit
`django_migrations`, or continue by disabling a health/security check.

## Required production values

Generate and store these in the production secret store before the window:

```dotenv
POSTGRES_USER=cafe_postcode
POSTGRES_PASSWORD=<database-owner-password>
DB_APP_USER=cafe_postcode_app
DB_APP_PASSWORD=<distinct-runtime-password>
DB_MONITOR_USER=cafe_postcode_monitor
DB_MONITOR_PASSWORD=<distinct-url-safe-monitor-password>
# Interactive Admin, Control, and Dashboard login is password-only for this
# release. Keep existing encrypted MFA rows and keys for rollback; do not expose
# or delete them.
ADMIN_MFA_REQUIRED=0
ADMIN_MFA_FERNET_KEYS=<existing-dedicated-key-if-present>
INTEGRATION_FERNET_KEYS=<different-dedicated-primary-key>
CLIENT_IP_TRUSTED_PROXY_CIDRS=<exact-reverse-proxy-cidrs>
DEVICE_POS_PROOF_REQUIRED=1
DEVICE_LEGACY_POS_MIGRATION_ENABLED=1
DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED=1
DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED=1
DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=1
# Never reopen legacy create/status/claim in production. Only already-paired TV
# credentials may use the bounded silent migration endpoint.
DEVICE_LEGACY_TV_PAIRING_ENABLED=0
DEVICE_LEGACY_TV_MIGRATION_ENABLED=1
DEVICE_LEGACY_MIGRATION_STARTED_AT=<cutover-UTC>
DEVICE_LEGACY_MIGRATION_DEADLINE=<cutover-UTC-plus-at-most-24-hours>
```

For the planned 2026-08-20 00:30 Asia/Tashkent window, the corresponding
values are `2026-08-19T19:30:00Z` and `2026-08-20T19:30:00Z`. Reconfirm the
actual start before release; do not silently extend a missed window.

`ADMIN_MFA_REQUIRED=0` disables enrollment, challenge, step-up, and per-request
MFA enforcement. It does not weaken password validation, session rotation,
idle locking, throttling, tenant scoping, or security-event logging. Business
Partner users may enter Control with the dedicated Control permissions, and
every branch/device query and mutation remains restricted to restaurants
assigned to their active partner. Superadmin retains global Control scope.

Keep every old `INTEGRATION_FERNET_KEYS` key after rotation, primary first,
until `rotate_integration_settings_keys` succeeds and the rollback window ends.
Losing a key makes stored integration credentials unrecoverable.

## Preflight and evidence capture

Run read-only checks first and attach their output to the rollout record. Never
print `.env.production` or any secret.

```bash
cd /home/postcode/backend
test -f .env.production
git status --short
git rev-parse HEAD
df -h /home/postcode /var/lib/docker
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production ps
docker compose --env-file .env.production images
bash ops/check-cloudflare-ranges.sh
```

The worktree must be clean, including untracked files. Record the old revision
and container image IDs in a new timestamped mode-0700 evidence directory
outside the repository before fetching; never overwrite evidence from an older
attempt. Deploy the exact SHA that passed CI in detached-HEAD mode; never build
the mutable tip of `production`, and do not rely on a mutable image tag for
rollback. Only after all health/security checks pass may the workflow atomically
promote `last_known_good_backend_revision` and
`last_known_good_backend_image`. The production deploy job must remain
serialized so two backup or migration sequences cannot overlap.

Create and verify the pre-deploy backup:

```bash
bash ops/backup-postgres.sh
```

The script writes a mode-0600 custom dump, validates it with `pg_restore --list`,
and creates a SHA-256 file. Copy the dump to the isolated rehearsal environment,
restore it into a newly created database, run all migrations there, and execute
representative smoke tests. Do not use the production database for rehearsal.
Before go-live, upload an encrypted copy and checksum to approved immutable
off-host storage and verify it can be read by the documented recovery identity.
This repository does not configure that storage provider; deployment remains
blocked until the owner selects and validates one. Add WAL archiving/PITR and a
failure alert as a separate operations control immediately after this release.

## Forward rollout sequence

The checked-in workflow follows this order. Execute manually only during an
approved recovery or supervised rollout. The device compatibility order is
strict: **backend first, signed bounded Bridge Agent second, refreshed POS
frontend third**. Deploying POS before a compatible Agent forces manual pairing;
deploying a final bridge-disabled Agent before old POS refresh breaks legacy
local access.

1. Validate Compose interpolation before changing containers.
2. Create the verified database backup.
3. Provision/rotate least-privilege runtime and monitoring roles:

   ```bash
   bash ops/provision-database-roles.sh
   ```

4. CI builds the verified revision once, publishes it to GHCR with provenance
   and an SBOM, runs a Django system-check smoke test against that exact digest,
   blocks on the pinned Trivy high/critical scan, signs the digest with GitHub
   OIDC, and records the immutable `name@sha256:...` reference. Authenticate
   with the pull-only production registry credential, verify the exact workflow
   identity and OIDC issuer with Cosign, then pull that digest. Never rebuild
   source on the production host. Export that exact reference as
   `BACKEND_IMAGE` for every following Compose command.
5. Inspect the migration plan. Unexpected migration names are a stop condition:

   ```bash
   docker compose --env-file .env.production --profile operations run --rm \
     migrate python manage.py showmigrations --plan
   ```

6. Run migrations with the owner role through the operations-only service. The
   migration connection should use a short PostgreSQL `lock_timeout` (recommended
   5 seconds) and a bounded `statement_timeout` (recommended 15 minutes). A lock
   timeout aborts the rollout before application replacement; investigate and
   reschedule instead of raising the timeout during peak traffic.

   ```bash
   docker compose --env-file .env.production --profile operations run --rm migrate
   ```

7. Verify the retained rollback schema, ciphertext completeness, and decryption
   with the release image. The command returns counts, never values:

   ```bash
   docker compose --env-file .env.production --profile operations run --rm \
     migrate python manage.py check_rollout_rollback_readiness
   docker compose --env-file .env.production --profile operations run --rm \
     migrate python manage.py check --deploy
   ```

   For independent SQL evidence, verify the encrypted backfill has no missing
   ciphertext rows. Return counts, never values:

   ```sql
   SELECT count(*) AS missing_ciphertext
   FROM integrations_integrationconfig
   WHERE settings_encrypted IS NULL;
   ```

   The required result is `0`. The old `settings` column intentionally remains
   during the rollback window.

8. Before the default-profile rollout, explicitly stop and remove the old
   high-privilege optional containers:

   ```bash
   docker compose --env-file .env.production --profile docker-admin --profile host-observability \
     stop portainer node-exporter cadvisor
   docker compose --env-file .env.production --profile docker-admin --profile host-observability \
     rm -f portainer node-exporter cadvisor
   ```

   Their named volumes are retained. Portainer moves to the `docker-admin`
   profile; node-exporter and cAdvisor move to `host-observability`. Host metrics
   and their alerts are degraded until a separately approved hardened replacement
   or explicit profile restart is in place. Record this monitoring gap.

9. Replace default-profile services, wait for health, and verify the runtime role:

   ```bash
   docker compose --env-file .env.production up -d --remove-orphans --no-build \
     --wait --wait-timeout 180
   docker compose --env-file .env.production ps
   docker compose --env-file .env.production exec -T web python manage.py check --deploy
   docker compose --env-file .env.production exec -T web python manage.py check_database_role
   ```

   Before this switch the workflow records the old web/ws/qcluster image,
   revision, and Compose definition. A switch or post-switch health failure
   automatically attempts the backward-compatible old image, then verifies the
   restored container health and image identity. The workflow remains failed
   even after a successful automatic rollback so an operator must investigate.
   A failed automatic rollback is a critical incident; follow the manual
   rollback procedure below. This image rollback does not reverse migrations
   and does not make the single-replica rollout zero-downtime.

10. Run the device finalization command in dry-run mode only:

    ```bash
    docker compose --env-file .env.production exec -T web \
      python manage.py finalize_device_migration
    ```

    Record `unbound_active_pos_sessions`, `unmigrated_active_local_agents`, and
    `unmigrated_active_tv_monitors`. The workflow must never add `--apply`.

11. Publish only the specially signed Bridge Agent whose embedded bridge
    deadline matches the server window and is no more than 24 hours from its
    build time. A normal/final Agent build has no legacy bridge and is not the
    migration artifact. For each branch, require all of the following before
    refreshing POS: Agent Device is ACTIVE, signed WebSocket heartbeat is
    online, migration summary reports `readyForPOSUpdate=true`, and the branch
    has a Control operator available for QR fallback.

12. Refresh the POS application without clearing browser site data or IndexedDB.
    The old six-character restaurant code may resolve only the pre-cutover
    restaurant context. It never issues a session, bearer token, or device
    identity. The existing Agent credential, Agent attestation, browser-held
    terminal identity, and new non-exportable browser key perform the silent
    migration. After successful binding the cashier signs in with PIN.

## Immediate live verification

Before declaring the rollout healthy, verify all of the following without
changing unrelated production data:

- `/healthz/` is healthy and web/ws/qcluster have no restart loop.
- A representative existing branch remains signed in and can unlock by PIN.
- One representative order can be opened, updated, paid, and printed.
- Existing Local Agents reconnect and commands remain tenant-scoped.
- Existing TV monitors migrate/reconnect; their retired token stops working only
  after successful generalized-device migration.
- Existing Telegram links still work; a newly issued link is one-use and expires.
- Admin, Control, and Dashboard accept password-only login; an MFA challenge or
  enrollment screen is a release mismatch. Business Partner Control lists only
  its assigned restaurants, while superadmin sees all permitted branches.
- A pre-cutover restaurant code returns only its restaurant/transport context;
  a code for a post-cutover restaurant or an expired migration window is denied.
- Error rate, latency, DB locks, queue backlog, and failed PIN/device-proof events
  do not spike above the agreed threshold.

Keep the previous application image, old revision record, backup, and every
encryption key for the full rollback window.

### Scrub retained plaintext integration settings

Migration `integrations.0013` keeps the old plaintext values only so the old
application can continue serving while the encrypted shadow is backfilled and
the new release starts. This is a deliberate, temporary confidentiality risk.

After the new application passes all production smoke checks, run the audit in
dry-run mode and archive only its counts:

```bash
docker compose --env-file .env.production exec -T web \
  python manage.py scrub_legacy_integration_settings
```

With separate explicit owner approval, scrub the values:

```bash
docker compose --env-file .env.production exec -T web \
  python manage.py scrub_legacy_integration_settings --apply
```

The command verifies ciphertext completeness and authenticates/decrypts every
envelope before changing anything. `--apply` locks the rows and NULLs the hidden
plaintext column in one transaction using bounded batches. It prints counts only.
The column remains for compatibility, and the reverse migration reconstructs its
values from ciphertext before old code is restored. Never add `--apply` to the
automatic deployment workflow.

## Bounded automatic migration window

During the at-most-24-hour window, review the dry-run and per-branch summaries
repeatedly. A legacy flag never overrides the start/deadline or creation cohort:
the application fails closed outside the interval.

Eligibility is frozen at cutover. Only restaurants, legacy Local Agents, and
legacy POS sessions/devices created at or before
`DEVICE_LEGACY_MIGRATION_STARTED_AT` can use silent compatibility. Anything
created after that instant must use Control QR pairing, even while the 24-hour
window is open. Do not implement automatic approval of arbitrary pending pairing
requests; the silent path is authenticated by pre-existing Agent credentials and
signed attestation, not by trusting a six-character restaurant identifier.

An Agent that is offline at 00:30 may migrate when it next comes online inside
the window. A POS browser also has to open or refresh while that Agent is online:
the Agent alone cannot create the browser's non-exportable key or complete the
terminal bind. If either side returns after the deadline, if its old browser
storage was cleared, or if the Agent cannot produce a valid signed attestation,
Control QR pairing is required.

### Garizon canary

Use Garizon as the first supervised branch because the owner controls both its
computer and phone. Keep a second Control-capable device available. Verify the
Agent has migrated and is online over the signed WebSocket, then refresh the
phone POS without clearing site data. Confirm silent bind, PIN login, one test
order/payment/print, offline queue/reconnect, and revoke rejection. The old
phone POS may be LAN/router-based, so updating the Agent before the phone has
loaded the new POS can temporarily break that terminal; schedule both actions
together and retain QR fallback.

Do not call finalization `--apply` until all expected branches have checked in,
all Local Agents/TVs are migrated or explicitly accounted for, and the owner
accepts that remaining unbound POS sessions will be revoked.

At cutover:

1. Run `finalize_device_migration` dry-run and archive the counts.
2. Resolve every unexplained unmigrated Agent/TV.
3. Obtain explicit owner approval.
4. Run `finalize_device_migration --apply` once to revoke remaining unbound POS
   sessions.
5. Set all `DEVICE_LEGACY_*` flags to `0`; keep
   `DEVICE_POS_PROOF_REQUIRED=1`.
6. Publish/use the final bridge-disabled Agent artifact.
7. Recreate application services and re-run the immediate verification list.

## Rollback

Rollback is a controlled incident action. First stop the rollout, preserve logs,
record the reason/time, and obtain approval. Never solve an application failure
by restoring the database backup first; that discards post-backup orders and
payments.

The deployment workflow automatically attempts and verifies an old-image
rollback for failures after the service switch. The steps below are for a failed
automatic rollback, a later regression, or an explicitly approved schema
rollback.

If migrations have not run, restore the recorded old image/revision and do not
change the database.

Container rollback is image-based, not Git-based: before the switch record the
exact immutable image digests and Compose definition for backend, Admin,
Control, Dashboard, and POS. Keep those images locally/pinned and restore them
with `--no-build`; verify container image identity and health after the switch.
This can restore server/frontend processes without a Git checkout, but it does
not reverse device state already consumed during silent migration.

For every canary/branch Agent, preserve the old signed EXE, its protected config,
and its Edge SQLite database together before update. The updater deletes
`.previous` after its health grace period; successful Agent migration removes
the legacy Agent credential, and successful POS secure-channel migration erases
the old browser/Agent bearer and discards the old unbound session. Therefore an
old Docker image or old Agent EXE alone is not an instant authentication rollback.
Restore that three-part Agent snapshot only as an approved incident action, or
keep the terminal on the new device identity/use Control QR pairing.

If migrations ran but the new application was not started, the old application
can still read its retained columns. For the most deterministic rollback,
freeze all writes, keep the current migration image and every Fernet key, and
reverse only these contract migrations in this order:

```bash
docker compose --env-file .env.production stop web ws qcluster
docker compose --env-file .env.production --profile operations run --rm \
  migrate python manage.py migrate integrations 0012
docker compose --env-file .env.production --profile operations run --rm \
  migrate python manage.py migrate kitchen 0008_tv_monitor_device_binding
docker compose --env-file .env.production --profile operations run --rm \
  migrate python manage.py migrate local_agents 0005
docker compose --env-file .env.production --profile operations run --rm \
  migrate python manage.py migrate restaurants 0024
```

These reversals restore plaintext integration settings, missing restaurant codes,
and missing TV hashes before restoring old constraints/state. They do not destroy
orders, payments, device rows, MFA rows, or security events. Verify row counts and
representative values through the old application, then start the recorded old
image. This rollback has a controlled service interruption; do not attempt it
while either old or new workers are writing.

Restore the database dump only when schema/data corruption is confirmed and the
owner explicitly accepts losing every write after the backup timestamp. Restore
into a separate database first, validate it, and switch only after reconciliation.

Optional high-privilege services are recoverable without deleting volumes:

```bash
docker compose --env-file .env.production --profile docker-admin up -d portainer
docker compose --env-file .env.production --profile host-observability up -d \
  node-exporter cadvisor
```

Enable them only when their host-level access is explicitly accepted.

## Deferred physical cleanup

Do not add `DROP COLUMN settings`, `DROP COLUMN auth_code`,
`DROP COLUMN restaurant_auth_code_hash`, or
`DROP TABLE local_agents_localagentenrollmenttoken` to this rollout.

A later contract release may remove those objects only after:

1. the device migration deadline and rollback window have elapsed;
2. two verified backups exist, including one made after cutover;
3. no rollback to the restaurant-code release remains supported;
4. all integration ciphertext rows are present and decryptable with the retained
   key set; and
5. the cleanup migration has been rehearsed on a current production-size restore
   with measured lock duration.
