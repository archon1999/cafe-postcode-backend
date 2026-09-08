# Sale units

`common/sale_units.json` is the single source of sale-unit IDs, quantity steps,
precision, localized abbreviations, input behavior and marking compatibility.
Django models, validation, inventory availability and report labels use
`common.sale_units`. Frontend code uses the generated `shared/domain/sale-units`
module. Local Agent embeds its generated JSON and applies `sale_units.go`.

After changing the contract, with the sibling repositories and their frontend
Node dependencies installed, run from the workspace:

```powershell
python backend/scripts/generate_sale_units.py
python backend/scripts/generate_sale_units.py --check
```

The generated files are committed in each independent repository so builds and
offline POS do not depend on accessing another checkout or a running backend.
Adding a unit also requires a Django choices migration and any new UI copy keys.
Do not add unit-specific branches in product forms, POS pages or report widgets.

A portion (`pors`) is sold in steps of 0.5. Zero is an empty selection in POS:
grouped selections omit it and the standalone dialog closes without creating a
row. Stored order rows must be positive. Existing piece and kg behavior is
preserved. Existing order rows validate against their snapshotted sale unit.

Verification covers admin choice/formatting, POS dialogs and optimistic totals,
backend creation/update and Agent replay, inventory minimums, and Local Agent
HTTP mutations with unavailable backend, lost acknowledgement and reconnect.
