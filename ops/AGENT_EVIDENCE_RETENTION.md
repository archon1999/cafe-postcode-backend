# Agent evidence retention

The reader always supports inline JSON and v1 references. The writer and jobs are
off without an explicit `AgentEvidencePolicy` for a restaurant. No POS or Agent
release is required; wire responses contain the exact original JSON body.

## Canary rollout

1. Deploy migrations and reader to **web, ws and qcluster** before enabling any
   policy. Do not roll back to a reader without reference support afterwards.
2. Configure a private store. For the first pilot set
   `AGENT_EVIDENCE_ARCHIVE_BACKEND=file` in production compose environment. The
   `agent_evidence` volume is mounted at `/app/agent-evidence` by the three
   application services. Nginx has no mount or route to it. Files are 0600 under
   a 0700 root. Keep this volume when recreating containers.
3. Select **one** restaurant, capture Payment/Refund/FiscalReceipt counts and
   amounts, journal hashes/timestamps and health. Dry run:

   ```sh
   python manage.py agent_evidence_retention --restaurant UUID --batch-size 25
   python manage.py agent_evidence_retention --restaurant UUID --configure pilot --archive --apply
   python manage.py agent_evidence_retention --restaurant UUID --batch-size 25 --archive --apply
   ```

4. Replay existing original v1/v2 envelopes and a Receipt-only legacy example.
   Assert exact old body/status, `replayed=true`, and unchanged business counts.
   A changed ID/hash combination must return 409, also during storage failure.
   Never invent a new payment ID to test replay in production.
5. Verify a private archive backup and health before expanding. Scheduling is a
   separate opt-in **after** the pilot:

   ```sh
   python manage.py agent_evidence_retention --restaurant UUID --configure schedule --apply
   ```

   Django-Q runs at 02:45, max 10 allowlisted restaurants, max 100 operations and
   20 seconds each. CLI defaults to dry-run, max 500 operations/120 seconds; hard
   limits 1000/240 seconds. A six-minute per-restaurant lease prevents concurrent
   jobs. Short transactions use 2s lock timeout and 15s statement timeout.
   Failure pauses that restaurant's scheduled job; retries remain idempotent.
   Cursors in the policy report make bounded runs progress past protected rows.

## Storage and retention invariants

- Inbox, Receipt and Attempt rows, original Inbox.operation, both hashes, sequence,
  epoch, dependencies and certificates remain. No identity guard is deleted.
- Successful bodies >=1024 bytes are shared by content hash **within an operation
  and restaurant**. New writes remain hot in DB and need no storage service.
- Existing settled successes are deduplicated after seven days. Distinct
  successful historical Attempt bodies retain their own content. Failures,
  conflicts, resolutions and PrintDocuments are not compacted in this rollout;
  this is more conservative than the proposed 90-day error retention.
- Only current successful responses go cold after 14 days, or 30 for billing.
  A recently received/applied/modified event or Attempt resets this floor.
  Resource closure must be proven. Open sessions/shifts/orders and unproven
  resource paths stay hot. Any unresolved Inbox, pending Payment, unfinished
  PrintJob or unsettled fiscal Receipt conservatively protects the whole branch
  from cold archival, including every unresolved dependency ancestor.
- Archives are bounded v1 JSONL+gzip, uploaded and read back with bundle and
  per-body SHA-256/length verification **outside transactions**. Finalization
  rechecks state and contents under short locks. A crash leaves either hot data
  or a verified archive. Unreferenced upload objects are retained for inspection.
- Archive read failures return retryable `EVIDENCE_TEMPORARILY_UNAVAILABLE`.
  They never clear the idempotency guard, redispatch payment/fiscal calls, return
  `{}` or rebuild a response from current business state. Independent operations
  continue. Do not force-reset outbox operations to bypass missing archives.

For S3 use `AGENT_EVIDENCE_ARCHIVE_BACKEND=s3`, a **separate** private
`AGENT_EVIDENCE_S3_BUCKET`, region and service IAM credentials. Upload requires
all four S3 public-access blocks, uses server-side AES256 and conditional
create. Configure bucket versioning/backups; no public media URL is used.

## Backup and recovery

`ops/backup-postgres.sh` now takes a matching private volume snapshot **after**
the DB snapshot and verifies both. Preserve `.dump`, `.evidence.tar.gz` and their
checksums together and copy them off-host. S3 objects require their own durable
bucket backup/versioning. A DB-only restore cannot recover cold response bodies.

Restore the private volume before serving a restored DB. Keep original restaurant
IDs, operation IDs, hashes and manifest keys; do not re-pair or clear journals to
repair missing payloads. Archive checksums are checked on each cold read.

For rollback to an older binary, keep the compatible reader deployed, pause the
restaurant, then rehydrate every journal:

```sh
python manage.py agent_evidence_retention --restaurant UUID --configure pause --apply
python manage.py agent_evidence_retention --restaurant UUID --rehydrate --apply
```

Verify no references remain for **any** enabled restaurant before deploying an
older reader. Rehydration restores original bodies and preserves journal
timestamps/hashes; it never executes a business operation or deletes archives.

Do not run `VACUUM FULL` in this job. PostgreSQL file sizes will not immediately
shrink; released tuple/TOAST space becomes reusable through normal autovacuum.
