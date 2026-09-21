# Service fee release and rollback

This release requires all participating Agents and POS clients to be updated.
There is no compatibility mode for old Agents. Local v3 is a development build,
not the signed production release. Lumen's production fee remains flat 100000
UZS/hour until the release and explicit assignment below are completed.

## Release order

1. Record immutable commits for backend, Admin, POS and Agent. Build the Agent
   from committed source using the existing signed release workflow. The local
   `formula-local-agent-v3.exe` must not be distributed as a signed release.
2. Publish the Agent/POS updates and verify the exact deployed version/commit on
   the target fleet, including Lumen. An offline branch returns with the new
   version before using formula configuration or newly published receipt rows.
   Updating is a release prerequisite; an intention to update is not evidence.
3. Before backend migration, run `ops/backup-postgres.sh` with the existing
   production environment and retain its verified dump/checksum. Record current
   service fee settings and published receipt-version IDs with the release.
4. Deploy the tested backend. Migrations restaurants 0030–0032, floor 0009 and
   printing 0015 add definitions, convert legacy hourly settings without changing
   the existing rounding policy, and publish the new receipt labels. Percentage
   configuration is not converted. Existing order/session snapshots are retained.
5. Deploy the Admin authoring interface. Assign the definition documented in
   `lumen-service-fee-formula.md` to Lumen's Kabina hall
   `d42cfef7-182b-474a-a162-d13750b86613`, restaurant
   `0f374e80-e171-401f-9a31-7d05b57af57c`. Use the ordinary validated assignment
   API and configuration invalidation. Verify the committed source/revision and
   Agent configuration refresh. Existing sessions retain their original snapshot;
   the new rate applies to newly opened sessions.
6. Check a new Lumen session/quote and a percentage branch receipt. Confirm that
   the formula receipt shows only `Xizmat haqi` and the amount, while percentage
   receipts retain the percentage. Check replay queues after connectivity returns.

OTAMAKON's test table fee was already disabled under the user's explicit request;
do not restore or re-enable it during this rollout.

## Rollback before formula business activity

Keep the new application source available while reversing its data migrations.
Pause new writes for the rollback window and verify Agent outboxes are drained.
Do not roll back application binaries first.

With unchanged auto-converted legacy configurations and no formula snapshots,
the following migration targets were rehearsed on PostgreSQL:

```text
python manage.py migrate restaurants 0031_service_fee_formulas
python manage.py migrate printing 0014_publish_item_line_totals
```

The first command reverses only automatic hourly conversion. It preflights all
three scopes and preserves enabled/rate/percentage fields. A changed or custom
formula blocks reversal until reviewed pre-release settings are restored. The
receipt reverse re-publishes the exact prior layout and keeps both versions;
edited layouts block automatic reversal. After successful data reversal, the
additive schema may be retained while application binaries are reverted. Do not
drop policy or definition columns just to change binaries.

## After formula orders or sessions exist

Keep a formula-capable backend and Agent: historic snapshots still require that
engine, even after orders close. Migration 0032 refuses reversal if it finds a
formula snapshot in an order or session. Instead, restore only the affected
branch's reviewed tariff for future sessions, retain all snapshots/payments and
fix the runtime forward. Preserve the accepted timestamp on paid orders.

A whole-database restore would discard business writes since backup. It is not
the normal tariff rollback and requires a separate outage/reconciliation plan.
Never use `--fake`, erase snapshots, or overwrite paid amounts to force reversal.
