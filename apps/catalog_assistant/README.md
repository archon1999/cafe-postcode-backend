# Catalog assistant and management bot

## Admin

`POST /api/v1/admin/catalog-assistant/drafts/` accepts multipart text, up to five
images or XLSX/CSV/TSV/TXT files. It reuses the inventory AI model/key/proxy
(`gpt-5.6-luna` by default). Source data is untrusted, response storage is off,
and the model has no mutation tools. The result is an owner-scoped 24-hour draft.

Review and commit require current restaurant access and catalog create permission.
Missing prices block saving. A commit validates every selected row and related
category, then saves atomically. Retrying a successful commit returns its saved
result. New categories require a reviewed MXIK; preparation routing can be set
in the category editor or bot. Inventory recipes remain separate.

## Telegram

The server-only `MANAGEMENT_BOT_TOKEN`, `MANAGEMENT_BOT_USERNAME`, and
`MANAGEMENT_BOT_WEBHOOK_SECRET` configure the separate management bot. Web and
qcluster must receive these values; qcluster also needs the existing inventory
AI configuration. Never put credentials in frontend variables.

The catalog page and business partner restaurant list issue a random, hashed,
one-use five-minute link. Issuing a new link invalidates older links. Consuming
it links one Telegram account to one user. Every action rechecks the current
user, role, entitlement, partner assignment and selected restaurant. `/disconnect`
removes the association.

Features: branch switching, category/product creation and updates, price,
stop-list, category/unit/preparation selection, AI draft review, zones, halls,
tables and capacities. Floor hiding is blocked for active primary or attached
table sessions. Changes require a one-use confirmation button. Layout positioning,
modifiers, recipes, and image editing remain in the full admin editor.

Webhook updates are durably deduplicated and dispatched to Django Q. Processing
locks the update and account; failed delivery rolls back its database writes.
Transient errors retry up to three attempts. Rejected updates retain an error
class, not source payload. Monitor `ManagementBotUpdate(status='rejected')`.

MXIK name search uses Tasnif's `/mxik/search/by-params?text=...`; the
`search-symbol` endpoint is typo suggestions and is unsuitable as primary search.
Inline results are personal and available only to linked, authorized users.
The bot owner must enable inline mode in BotFather using `/setinline`.

## Deployment checks

GitHub secrets `MANAGEMENT_BOT_TOKEN_B64` and
`MANAGEMENT_BOT_WEBHOOK_SECRET_B64` are synchronized to the private production
environment by the existing deployment workflow. CI runs catalog, bot and
snapshot tests against PostgreSQL before deployment.

After migrations and healthy service startup:

```
python manage.py configure_management_bot --webhook-url https://cafe-postcode.uz/api/v1/management-bot/webhook/
python manage.py check_catalog_assistant --live-ai --webhook-url https://cafe-postcode.uz/api/v1/management-bot/webhook/
```

The check extracts three synthetic products from text, XLSX and PNG without
saving catalog data, then verifies the public webhook and worker using an ignored
non-private update. It prints no credentials or customer data.

## POS offline behavior

This feature writes existing catalog/floor models and emits configuration
invalidation after commit. No new offline schema or POS mutation is introduced.
The existing menu and floor configuration snapshots include the new values;
Local Agent configuration refresh retains local orders, sessions and queued
operations and continues serving its cached configuration offline.
