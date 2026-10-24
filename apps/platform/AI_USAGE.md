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
Unrecorded calls are never invented. `trackingStartedAt` is the first live provider audit;
historical recovery never moves that date backwards.

## Historical recovery

`recover_ai_usage_history` is a read-only dry run unless `--apply` is supplied.
Applying requires `--expected-count` from a reviewed production dry run. It imports only
nonempty `CatalogDraft` rows created before the original usage migration (and before
the first live audit, if earlier). Creating these drafts required a successful, validated
provider response. HTTP access entries alone are not sufficient: input validation and
inventory cache hits do not prove provider attempts.

Recovered rows have source `catalog_draft`, a unique stable recovery key, deterministic
UUID, import time and a metadata-only source UUID/date basis. Their report date is the
original draft creation time; model is `unknown`, and token counts, cost and duration
remain NULL. Source rows, products, stock and existing usage are unchanged. Repeating
the command does not add duplicates; expected-count/evidence conflicts fail before
writes, and the batch runs atomically with a PostgreSQL advisory lock.

`ops/inspect-ai-history.py` inventories retained Postcode container/access logs and draft
metadata without exporting prompts, uploaded content or credentials. Its private JSON
report stays mode 0600 on the host. Matching Nginx requests are corroboration only and
are not imported as additional rows alongside their drafts. `recoveredRequestCount`
is included in summary metrics; each history row exposes `source`, `recoveredAt` and
safe `evidence`. The initial recovery leaves unknown amounts NULL.

### Owner-confirmed historical estimates

After the owner confirmed that all recovered menu calls used `gpt-5.6-luna` and
explicitly requested approximate usage, `estimate_ai_usage_history --model=gpt-5.6-luna`
provides a read-only preview. Apply requires `--apply --expected-count=<reviewed count>`.
Only recovered `catalog_draft` rows with no existing usage measurements are enriched.
Live measurements are never changed. Repeated runs freeze already estimated rows,
even if drafts, prompts or pricing configuration change afterwards.

Method `catalog_draft_text_v1` projects saved rows onto the original AI output fields,
excluding review flags, category UUIDs and MXIK bookkeeping. It uses compact UTF-8 JSON
for output, deduplicated saved source excerpts, saved category names, and the current
menu instructions/schema as a proxy for historical input. Each side is approximated
as `ceil(UTF-8 bytes / 4)`, with 16 framing tokens on input. Saved rows may have been
edited after extraction. This is a rough text-based estimate, not a bound on billing:
original images/files, full category context and hidden reasoning were not retained.

`model` is operator-confirmed. `usage_is_estimated=true` marks the populated token/cost
fields. Cached tokens and duration remain NULL; pricing assumes no cache discount and
records this assumption. Version, byte sizes, timestamp and missing components are
retained as metadata; no source content is copied to usage logs or operation output.
Each estimate includes a frozen verified/overridden Standard rate snapshot.

All summary dimensions include estimates and expose `estimatedUsageCount` and
`estimatedTokenCount`, so clients mark mixed/estimated token and USD totals with `≈`.
Request rows expose `usageIsEstimated` and a safe `usageEstimation` explanation.
Deployment operation `estimate_ai_history` verifies the exact source/image, takes
private before/after snapshots, and checks live rows, provenance, count, sums and cost.

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
