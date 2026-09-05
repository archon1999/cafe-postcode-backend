# Financial flow v2 release

The assigned, paired Local Agent owns financial execution both online and offline. Cloud endpoints dispatch a stable command to that owner. The backend atomically stores an immutable inbox event and projects its result; it does not call a fiscal device inside a database transaction. A received event is not reported as applied until the projection commits.

Original operation, payment, shift, fiscal-session and occurrence identities survive retries. Cross-shift dependencies prevent a successor opening from overtaking the preceding close. Closed-shift payments remain in the original shift and create a reconciliation record rather than moving into today's cash balance. Closed financial totals cannot be rewritten by kitchen updates. The first hourly payment persists its original service-fee freeze time.

Fiscal failures retain their fiscal intent and evidence. Unknown device outcomes cannot be converted into an ordinary receipt or silently retried as a new charge. A full-order refund uses the original aggregate fiscal receipt and records each tender separately. Plain refunds also retain a printable document. Operator repairs must preserve original request hashes, failed responses and fiscal proofs; dismissing a failed queue request does not annul an OFD receipt or complete a refund.

## Deployment contract

Deploy this backend together with the corresponding POS/admin changes and Agent 1.2.1. Run billing migrations `0016`, `0017`, `0018` and local_agents `0009`. `makemigrations --check --dry-run` must remain empty. Strict paired-device proof stays enabled. Every branch must upgrade; no previous financial execution path is re-enabled to support old agents.

Use a planned cashier cutover: preserve the database and each Agent journal/configuration, settle or explicitly resolve existing uncertain operations, migrate the backend, publish the paired POS/admin and signed mandatory Agent release, and verify each branch's version/capability/identity before reopening sales. Publishing the Agent manifest separately while old backend/POS code remains active is not a complete rollout.

Check cash/fiscal shift agreement, zero actionable/unknown financial operations, completed inbox/outbox synchronization, OFD acknowledgements and accepted print jobs. Offline branches require the same check after reconnecting. Keep original closing reports immutable when repairing historical sales; review the separately recorded reconciliation deltas. Do not close a historical physical shift merely to clear a warning.

## Validation

The focused release suite passed 169 tests covering signed Agent HTTP/WebSocket authentication, durable mutation/inbox behavior, payment projection, financial evidence, command status, admin routing, open checks and expenses. Twelve cashier shift/report/refund cases were also migrated to the owner projection contract; the final 32-test refund/shift/evidence regression run passed. This is 181 distinct relevant backend cases across the runs, not a claim that every repository test ran.

The earlier local POS acceptance covered 52 physical fiscal sales, 5 physical full-order refunds, six closed shifts and 100 applied events with no remaining OFD/outbox/inbox items. It was iterative across candidate builds. Bank hardware was explicitly excluded; Windows print-spool acceptance was the requested printer criterion. Detailed test and production-repair evidence is retained in the local September 5 audit directory, outside committed credentials and runtime state.
