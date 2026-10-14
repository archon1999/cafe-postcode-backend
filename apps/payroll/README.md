# Staff payroll

The app is mounted at `/api/v1/staff/payroll/`. All routes require an active
staff access session, an active tenant, and `GeofenceConfig.workforce_enabled`.
Manager reads require `staff.payroll.view`, calculations and adjustments require
`staff.payroll.manage`, and payment recording/voiding requires
`staff.payroll.payout`. A staff member's `me/` routes show only that member's
locked payroll snapshots.

Manager routes:

| Route | Method | Purpose |
| --- | --- | --- |
| `periods/` | GET, POST | List/create nonoverlapping payroll periods |
| `periods/<id>/` | GET | Latest employee runs, adjustments, payments |
| `rates/` | GET, POST | Effective-dated employee rates |
| `kpi-rules/` | GET, POST | Branch default or role-specific POS percentages |
| `periods/<id>/runs/build/` | POST | Recalculate one employee or all employees with rates (`employeeId` optional) |
| `periods/<id>/runs/lock/` | POST | Reject unresolved timesheets/adjustments, refresh, then freeze latest runs |
| `periods/<id>/adjustments/` | POST | Create a pending manual KPI, bonus, advance, penalty, deduction, or signed correction |
| `adjustments/<id>/approve/`, `adjustments/<id>/reject/` | POST | Decide a pending adjustment |
| `periods/<id>/kpi-preview/?employeeId=<id>` | GET | Show attributable net sales and KPI amount |
| `periods/<id>/kpi-approve/` | POST | Approve or replace a changed POS KPI before first lock |
| `periods/<id>/payouts/` | POST | Log a manual cash or external transfer payment |
| `payouts/<id>/void/` | POST | Void a mistaken ledger entry with a reason |

All request and response keys use the API's camelCase JSON convention.

Hourly rates multiply approved minutes/60; daily rates multiply approved shift
counts. A monthly rate is a fixed base for the payroll period, independent of
attendance and period length. If the contracted rate changes within the period,
its old and new values are weighted by their effective days. Unpaid leave and
other deductions are explicitly approved adjustments.

An `advance` adjustment records money already handed to the employee and
requires `paymentMethod` (`cash` or `external_transfer`) and `disbursedAt`.
It reduces the later payroll total once approved. The advance must not also be
entered as a regular payroll payout, which would subtract it twice.

POS KPI looks at closed orders in the period and only noncancelled items.
Successful payments minus successful refunds are allocated across merchandise
by line value. Service fees are excluded using the merchandise share of the
original calculated check. Items with no creator still participate in the
allocation, but earn no employee KPI. Approval captures the calculation as an
adjustment. Before the first lock, a refund, payment change, or rule change
invalidates that approval: locking fails until a manager reviews and approves
the new snapshot. The old approval is retained as superseded. A full refund
can remove the approved KPI line. After a lock, POS KPI changes require an
explicit manual correction and a new locked version; prior runs remain intact.

Payouts are audit records only. Recording `external_transfer` never contacts a
bank. The sum of active payout entries cannot exceed the latest locked run.
Voids retain the original entry and its reviewer/reason. A revised run cannot
be locked if its new total would fall below payouts already recorded. Staff
continue to see the preceding locked version until that conflict is resolved.
Negative net payroll also blocks locking so deductions must be reviewed first.
