# App Internal Architecture

This document describes the internal structure expected inside one refactored backend app.
The concrete example below uses `backend/apps/sales`, but the same layering rules apply to the other domain apps.

## Target Shape

```text
backend/apps/sales/
  api/
    admin/
      urls/
      views/
      serializers/
    pos/
      urls/
      views/
      serializers/
  models/
  selectors/
  services/
  helpers/
  constants/
  enums/
  tests/
    support/
  migrations/
```

## Responsibilities

### `models/`

- Owns database state for the app.
- Contains Django model definitions, queryset helpers tightly bound to the model, and model-level invariants.
- Does not know about HTTP, request headers, or endpoint-specific payload shaping.

### `selectors/`

- Read side only.
- Builds filtered querysets, annotations, aggregates, and detail loaders.
- Returns domain objects or pre-shaped read models.
- Does not perform writes or orchestration.

### `services/`

- Write side and business orchestration.
- Owns transactions, state transitions, and cross-model workflows.
- Calls selectors/helpers when needed.
- Can depend on other apps only through their public models, selectors, or services.
- Must not reach back into removed legacy apps.

### `helpers/`

- Small app-local adapters.
- Payload normalization, shared validation fragments, mapping utilities, and tiny bridge code.
- Not a dumping ground for business flows.

### `api/*/serializers/`

- Validates request payloads and shapes response payloads.
- Can call helpers for transformation.
- Must not contain cross-aggregate business transactions.

### `api/*/views/`

- Thin transport layer.
- Auth, permission checks, serializer selection, service/selector invocation, and HTTP response mapping.
- Should not duplicate business rules from `services/`.

### `constants/`

- Stable literals such as permission codes, defaults, and exported field groups.

### `enums/`

- Typed enums and Django `TextChoices`.

### `tests/`

- App-owned contract, unit, and integration tests live next to the owning app.
- Shared app-local fixtures/helpers go into `tests/support/`.
- Cross-domain tests are still placed under an owning app, never in a global `common/tests` bucket.

## Dependency Rules

Allowed direction:

```text
api -> serializers -> helpers
api -> selectors
api -> services
services -> selectors
services -> helpers
selectors -> models
services -> models
tests -> any app public surface needed for verification
```

Avoid:

- `views` importing old gateway or removed legacy apps.
- `selectors` performing writes.
- `services` hiding HTTP concerns inside business logic.
- `serializers` performing multi-model orchestration.
- creating a new global integration-test bucket outside app ownership.

## Example: `apps.sales`

- `models/` owns `Order`, `OrderItem`, and `OrderItemNote`.
- `selectors/` reads order lists, detail payloads, and status-sensitive querysets.
- `services/` owns order number sequencing, order state changes, submission flow, and item mutations.
- `api/pos/` exposes waiter and cashier order endpoints.
- `tests/` verifies serializer shape, service behavior, permission branching, and smoke flows.
- `tests/support/pos_api.py` provides reusable POS test setup, but it still belongs to the app tree instead of a global shared test package.

## Practical Rule

When adding code to an app, pick the layer by asking one question:

- "Is this read logic?" -> `selectors/`
- "Is this write/orchestration logic?" -> `services/`
- "Is this transport or payload code?" -> `api/*`
- "Is this a tiny local adapter?" -> `helpers/`
- "Is this persistence?" -> `models/`

If a file does not fit one of those answers cleanly, the design should be reconsidered before adding it.
