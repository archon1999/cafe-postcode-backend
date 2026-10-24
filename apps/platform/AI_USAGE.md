# AI usage accounting

`AIUsageLog` stores metadata for actual OpenAI provider attempts in catalog menu extraction,
inventory recommendations, inventory document preview, and service fee formula drafts.
The resolved restaurant, business partner and operator are recorded with their display-name snapshots.
Unscoped management calls remain explicitly unscoped. Local inventory cache hits do not create another paid request.
Config/input validation before a provider attempt is not billed usage and creates no usage row.

The record contains the provider model, success/error, request/response identifier, optional token counts,
duration, safe fixed error classification and optional USD estimate. It never contains a prompt,
provider output, uploaded document, API credential or upstream error message. Incomplete/invalid output
can still contain chargeable provider usage and therefore keeps its token counts.
No unrecorded historical calls are inferred. `trackingStartedAt` is the first recorded call.

## Pricing

Checked-in Standard API rates were verified on **2026-10-24** against the
[official OpenAI pricing page](https://developers.openai.com/api/docs/pricing).
Rates are USD per one million tokens; only these exact model IDs are recognized:

| Model | Input | Cached input | Output | Long input | Long cached input | Long output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-5.6-luna` | 0.20 | 0.02 | 1.20 | 0.40 | 0.04 | 1.80 |
| `gpt-5.6-terra` | 2.00 | 0.20 | 12.00 | 4.00 | 0.40 | 18.00 |
| `gpt-5.6-sol` | 4.00 | 0.40 | 20.00 | 8.00 | 0.80 | 30.00 |

Long rates apply to the whole request when its **actual input tokens exceed 272,000**.
Exactly 272,000 uses short rates. Input includes cached tokens; output does not affect tier selection.
Aliases, dated model variants and other unknown model IDs are not guessed.

Optional per-model overrides use the server environment variable (JSON), or Django setting:

```
AI_USAGE_PRICING_USD_PER_MILLION={"exact-provider-model-id":{"input":"2","cached_input":"0.5","output":"4"}}
```

The numbers in this override example are illustrative. A Django setting, when present, takes
precedence over the environment variable. Exact-model override entries take precedence over the
checked-in card; other models retain their defaults. An empty map/string means no overrides.
Legacy flat overrides apply their supplied rates to every context size. Invalid explicit
configuration/rates remain unpriced instead of silently falling back.

The estimate is `(input - cached_input) * input_rate + cached_input * cache_rate + output * output_rate`,
divided by one million. Input tokens already include the cached subset. The explicit rate snapshot
includes the source, verified date, tier and threshold for Standard defaults, or identifies an
operator override. The row keeps this snapshot, so later configuration changes do not rewrite history.
Missing/invalid token counts, inconsistent totals, missing cache splits and unknown rates remain
unpriced. Explicit zero counts/cost are valid. USD estimates are not invoices and are never converted to UZS.
Audit database errors produce a safe warning and do not change the business response; monitor this warning.

### Estimate already recorded, unpriced usage

`python manage.py backfill_ai_usage_costs` is a **read-only dry run** by default (also `--dry-run`).
Review its eligible/skipped counts and USD subtotal, then pass `--apply` to persist estimates.
It only updates `AIUsageLog.estimated_cost_usd`, its `pricing` snapshot and `updated_at`, for OpenAI
rows whose cost is NULL and whose recorded input/cached/output/total counts are complete and consistent.
Both successful and failed requests may have billable usage. It never calls a provider or changes
stock, products, documents, payments or settings. Already priced rows (including zero) are never
overwritten, even when rates change; repeated execution is idempotent. Backfilled estimates use
the current verified/overridden rate card, not an inferred historical invoice price.

## Read API

Superadmins only; other platform, partner and restaurant roles are denied even when staff.
There are no write endpoints, budget enforcement, or cost overrides.

- `GET /api/v1/admin/ai-usage/summary/`
- `GET /api/v1/admin/ai-usage/requests/`

Both accept `from`/`to` timezone-aware ISO timestamps with half-open `[from,to)` semantics
(default last 30 days, maximum 366 days), `restaurant_id`, `business_partner_id`, `model`,
`feature`, `status` (`success`/`error`) and metadata-only `search`.
Global reporting intentionally ignores the ambient `X-Admin-Restaurant-Id` header; only explicit
query branch/partner filters apply. This avoids silently narrowing the all-branches overview.
Daily trend buckets use Asia/Tashkent. Summary groups are bounded to 100 rows per dimension and
set `groupsTruncated` when limited. Filter options retain date/branch/partner scope while ignoring
model/feature/status/search selections.

Requests additionally accept `page`, `page_size` (1–100), and a single safe `ordering` field:
`created_at`, `duration_ms`, `total_tokens`, `estimated_cost_usd`, with optional `-` prefix.
Null numeric values sort last. Results use camelCase, with `count`, `page`, `pageSize`, `results`.
Summary totals/groups include request and status counts, known token sums, priced/unpriced request
counts and missing usage counts. `estimatedCostUsd` is a priced subtotal with explicit unpriced
counts, null when every actual request is unpriced, and zero for an empty range.

Migration `platform.0014_ai_usage_log` must be applied before enabling this code in a runtime.
This is online admin/cloud accounting. POS Local Agent offline parity is not applicable;
no stock, orders, payments or offline replay contracts change.
