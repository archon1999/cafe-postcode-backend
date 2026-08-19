# 2026-08-20 00:30 device migration checklist

This checklist prepares the requested Asia/Tashkent maintenance window. It is
not approval to touch production. Stop at any unchecked hard gate.

## Frozen contract

- Admin, Control, and Dashboard use password-only interactive login.
- Existing MFA rows and encryption keys are retained only for rollback. With
  `ADMIN_MFA_REQUIRED=0`, all MFA enrollment/challenge/step-up endpoints return
  `410 mfa_disabled` and recent-MFA permissions are not required.
- An active Business Partner can use Control, but only for restaurants assigned
  to that partner. Superadmin keeps global Control scope.
- The six-character restaurant code exists only during the bounded migration
  window and returns restaurant/transport context. It is not a password and
  never issues a bearer, session, Edge token, or Device identity.
- Silent migration applies only to records created at or before the cutover
  timestamp. Restaurants, Agents, POS sessions, and devices created after the
  cutover require Control QR pairing.
- Never auto-approve an arbitrary pending pairing request. Existing terminals
  migrate without operator pairing only when the pre-existing Agent credential,
  signed Agent attestation, old terminal state, and new terminal key all verify.

## Window values

Planned start:

```text
Asia/Tashkent: 2026-08-20 00:30:00 +05:00
UTC:           2026-08-19T19:30:00Z
```

The effective deadline must be the earliest of:

1. `start + 24 hours`;
2. `Bridge Agent builtAt + 24 hours`;
3. the staffed operational end time.

The backend start/deadline and the signed Bridge Agent `notAfter` must match the
same effective deadline. Do not extend an already-started window.

## Hard gates before 00:30

- [ ] Every repository is clean, committed, pushed, and the exact approved SHA
      is recorded. Local dirty files are not a release artifact.
- [ ] Backend, Admin, Control, Dashboard, POS, and Local Agent CI are green for
      those exact SHAs.
- [ ] The special Bridge Agent is Authenticode-signed and its embedded
      source SHA, `builtAt`, and `notAfter` have been verified. A normal/final
      bridge-empty Agent is not suitable for the migration phase.
- [ ] Immutable image digests for every web application are recorded. The old
      digests and old Compose definition are present on the production host for
      `--no-build` rollback.
- [ ] A fresh production PostgreSQL custom dump has a verified checksum, a real
      restore rehearsal, and an encrypted immutable off-host copy.
- [ ] Per-branch protected backup instructions exist for old Agent EXE + config
      + Edge SQLite DB. Test one restore on a non-production machine.
- [ ] Current free disk, database locks, health, error rate, and queue backlog
      are acceptable.
- [ ] Garizon has a second Control-capable device and a manual QR fallback.
- [ ] No branch creates a new Agent/POS between cohort freeze and the switch
      unless operators accept that it will require QR pairing.

Any unchecked item is **NO-GO**.

## Production values

Use the actual effective deadline computed from the signed Agent artifact:

```dotenv
ADMIN_MFA_REQUIRED=0
DEVICE_POS_PROOF_REQUIRED=1
DEVICE_LEGACY_POS_MIGRATION_ENABLED=1
DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED=1
DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED=1
DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=1
DEVICE_LEGACY_TV_PAIRING_ENABLED=0
DEVICE_LEGACY_TV_MIGRATION_ENABLED=1
DEVICE_LEGACY_MIGRATION_STARTED_AT=2026-08-19T19:30:00Z
DEVICE_LEGACY_MIGRATION_DEADLINE=<verified-effective-UTC-deadline>
```

Keep POS device proof required throughout. Do not create a proof-off phase.

## Deployment order

1. Freeze changes and capture the current revision, Compose definition, running
   container IDs, and immutable image digests.
2. Create/verify the current backup and off-host copy.
3. Pull and verify all new immutable artifacts without switching services.
4. Run backward-compatible migrations and rollback-readiness checks.
5. Switch backend/websocket/worker to the verified new digest and verify health.
6. Verify password-only Admin, Control, and Dashboard login. Verify a Business
   Partner sees only its assigned restaurant IDs in Control.
7. Release the signed bounded Bridge Agent to **Garizon only**. Agent `/health`
   is insufficient: require ACTIVE Device, valid lease, signed WebSocket online,
   heartbeat, and migration summary readiness.
8. Refresh Garizon POS on the controlled computer and phone without clearing
   site data/IndexedDB. Confirm silent bind, old bearer rejection, PIN login,
   order, payment, print, offline queue/reconnect, and Control revoke.
9. If Garizon is green, roll the Bridge Agent branch-by-branch. An offline Agent
   can migrate when it returns within the window.
10. Refresh POS branch-by-branch. Agent-online alone is not enough; each browser
    must open/refresh while the Agent is online to generate/bind its local key.
11. Deploy the remaining Admin/Control/Dashboard frontend artifacts and verify
    navigation, partner scope, branch connect, and revoke.
12. Monitor per-branch migration summary continuously. Do not finalize early.

## Expected compatibility behavior

| Situation | Expected result |
| --- | --- |
| Pre-cutover Agent returns online inside the window | Silent Agent migration is allowed |
| Pre-cutover POS opens inside the window with old browser/Agent state | Silent device migration, then PIN login |
| Six-character code is correct inside window | Context only; no authentication token |
| New restaurant/Agent/POS created after cutover | Control QR pairing required |
| Old browser storage was cleared | Control QR pairing required |
| Agent is unavailable during POS migration | Fail closed; retry when Agent is online or pair by QR |
| Any legacy path after deadline | Denied; Control QR pairing required |

## Container rollback without Git rollback

On application failure before device state is consumed, set each Compose image
variable to the recorded old immutable digest and run the old recorded Compose
definition with `--no-build`. Verify exact running digest and health. Do not use
`git pull`, mutable tags, or rebuild source on the host.

After a terminal successfully migrates, server containers alone cannot restore
the old authentication state: old Agent credentials and old POS bearer/session
are deliberately retired. For an Agent incident, restore the matching old EXE,
protected config, and Edge SQLite snapshot together, or keep the terminal on the
new identity/use Control QR. Never restore the production database merely to
undo authentication migration; that would discard new orders/payments.

## End of window

1. Archive migration summary and account for every branch.
2. Require explicit owner approval before `finalize_device_migration --apply`.
3. Revoke remaining unbound legacy POS sessions.
4. Set every `DEVICE_LEGACY_*` flag to `0` while keeping
   `DEVICE_POS_PROOF_REQUIRED=1`.
5. Publish the final bridge-empty Agent and verify representative branches.
6. Keep old images, Agent snapshots, database backup, and encryption keys for
   the approved rollback-retention period. Physical schema cleanup is a later
   release.
