# Restaurant inventory

Admin UI: `/restaurant-admin/inventory`. API contract: [CONTRACT.md](CONTRACT.md).

Apply the normal Django migrations before starting the updated Daphne backend.
Compile the updated message catalogs with
`poetry run python ops/compile_translations.py` before restarting a local backend.
The Docker build compiles these catalogs automatically.
The five `admin.inventory.*` permissions are seeded through the existing role and
entitlement workflow. Viewing cost, editing drafts, posting documents and AI
analysis are separate permissions. Every query is scoped to a restaurant.
Original attachment downloads also require cost access, because invoices may
contain prices. Document responses and exports hide attachment URLs without this
permission; editing other draft fields preserves the existing attachment.

## Operating the feature

1. Create ingredients in grams, millilitres or pieces. Define the purchase unit
   and conversion factor: for example, 1 kg = 1000 g. Configure minimum stock and
   the operational variance thresholds. `off`, `warn` and `block` control stock
   availability; existing manual stop lists remain independent.
2. Create an opening balance or receipt, enter the source reference, date,
   responsible person and supplier where required. Attach a PDF or photo if
   needed. A draft changes no stock. Post the reviewed document to create ledger
   movements. Corrections create a linked reversal; posted lines are immutable.
3. Link a menu item to a recipe with gross ingredient quantities and recipe yield.
   A modifier line adds ingredients only when that option was selected. Each edit
   creates a version. Prepared food consumes at dispatch; stocked finished goods
   may consume when fully paid. Quantity validation is repeated on the server.
4. Choose what happened when cancelling a consumed item: `not_prepared` or
   `returned` restores the original ingredients/cost, while `waste` preserves the
   consumption. A financial refund alone does not create physical stock. Use an
   explicit customer return document for a physical return after payment.
5. Start a count to capture the expected balances and ledger revisions, then
   enter every measured quantity (including an explicit zero). Posting rejects
   uncounted lines or intervening movements. Recount if operations changed the
   snapshot. Variance percentage uses recipe consumption since the previous
   count; with no consumption it is unknown, not zero.
6. Review balances, values, movement history, count variances and evidence-backed
   recommendations. CSV exports include source document and actor context.

Balances and values are estimates from recorded movements. Weighted average
costing uses exact decimal arithmetic. Operational tolerances are management
alerts, not statutory natural-loss allowances. Application confirmation is not an
electronic digital signature, and this module does not replace EHF or fiscal
receipt integrations. The company defines its accounting/document policy.

## Optional OpenAI analysis

Set `INVENTORY_AI_API_KEY` (or the existing `OPENAI_API_KEY`) and
`INVENTORY_AI_MODEL` in the **backend environment**, using a model available to
your API project that supports Responses structured outputs. Never put these
values in frontend variables. Restart Daphne after changing the environment.

The analysis endpoint sends up to 60 current recommendation facts from the
selected restaurant to `https://api.openai.com/v1/responses`, with `store: false`.
It sends no employee names, supplier bank details or attachment contents. The
model receives no write tools. Its structured response must cite existing
evidence IDs. A five-minute cache and six-requests-per-minute user limit reduce
duplicate requests. Provider failure leaves the stock ledger untouched and
returns an explicit unavailable response; rules continue to work without a key.

Viewing inventory, viewing cost and the analysis permission are all required.
The user-triggered AI result is advisory and is never automatically posted as a
stock movement or used to accuse a staff member of misconduct.

## Offline and reconciliation

Deploy compatible backend, POS and Local Agent versions together. Bootstrap and
operational snapshots carry recipes, stock and active consumption lineages.
The Agent stores order state, ingredient changes and its outbox atomically.
Dispatch replay supplies the original immutable recipe and warehouse identities;
the server validates them before accepting already-consumed offline activity.
Replay and stock returns are idempotent. Pending operations fence canonical
snapshot replacement to avoid applying the same deduction twice.

A physical count can precede a delayed offline delivery. In that case the late
movement remains visible and a critical recount recommendation is shown. Until a
new count resolves it, the current balance may include consumption already
covered by the physical count. Avoid counting while terminals still have pending
outbox entries. A later count clears the warning for the affected ingredients.

Batch expiry fields are documentary warnings; they do not claim an exact
remaining quantity per batch. FEFO, manufacturing of intermediate products,
automatic OCR and inter-warehouse transfer documents are separate extensions.

Tests: `poetry run python manage.py test apps.inventory
apps.sales.tests.test_inventory_integration apps.sales.tests.test_pos_order_queryset`.
Local HTTP/offline verification instructions are in
`local-agent/scripts/edge-inventory-client.md` in the workspace.
