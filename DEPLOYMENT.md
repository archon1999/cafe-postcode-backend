# Backend Deployment

## Docker Compose Production Stack

Production is prepared for Docker Compose with:

- `web`: Django + Gunicorn on `0.0.0.0:8000`
- `ws`: Django Channels + Daphne on `0.0.0.0:8888`; Nginx proxies only `/ws/` here
- `qcluster`: Django Q worker
- `postgres`: PostgreSQL
- `redis`: cache, channel layer, and Django Q broker
- `nginx`: public reverse proxy; `/metrics` is blocked externally
- `prometheus`, `grafana`, `postgres-exporter`, `redis-exporter`: monitoring

Use the example only to prepare secrets in an approved environment. **Never run
`docker compose up` directly in production.** Every production rollout must
follow [`ops/DEVICE_MIGRATION_RUNBOOK.md`](ops/DEVICE_MIGRATION_RUNBOOK.md), use
the manually approved GitHub production environment, and deploy the exact
CI-scanned, OIDC-signed image digest.

For a disposable local environment only:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production up -d --build
```

The `web`, `ws`, and `qcluster` services use a least-privilege runtime database
role and never run migrations. The operations-only `migrate` service uses the
separate migration credential, lock timeout, and statement timeout before any
application replacement. Prometheus scrapes Django metrics directly on the
internal Docker network at `web:8000/metrics`.

Docker Nginx routes normal HTTP/API traffic to Gunicorn and WebSocket traffic to Daphne:

- `/ws/` -> `ws:8888`
- everything else -> `web:8000`

By default Docker Nginx binds to `127.0.0.1:8880` so it can run behind the host Certbot/TLS Nginx. The host-level `cafe-postcode` Nginx config is stored at `nginx/cafe-postcode.uz.conf` and included by the host Nginx service.

The `admin.cafe-postcode.uz` virtual host keeps the existing Admin SPA on
`127.0.0.1:4200` and routes only `/control/` to the separately deployed Control
PWA on `127.0.0.1:4500`. Deploy and health-check the Control container before
installing/reloading this host config. The Control PWA must use the same
`https://cafe-postcode.uz` API origin as Admin so both clients share the existing
`__Host-cafe_admin_refresh` cookie family; do not proxy Control API calls through
the UI origin as a separate cookie scope.

## Required Production Settings

`DJANGO_PRODUCTION=1` enforces:

- `DEBUG=0`
- explicit `ALLOWED_HOSTS`
- strong `SECRET_KEY`
- PostgreSQL via `DB_ENGINE=postgres`
- `REDIS_URL`
- distinct runtime and database-admin roles
- dedicated Admin MFA and integration-encryption Fernet keys
- trusted proxy CIDRs and fail-closed device migration settings

The production Compose defaults expect TLS to be terminated before or at Nginx:

```bash
SECURE_SSL_REDIRECT=1
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
```

For local HTTP-only smoke tests, temporarily set those three values to `0` in `.env.production`.

API docs and the browsable API must remain disabled in production.

Faktura-backed company lookup requires these credentials in `.env.production`:

```bash
FAKTURA_USERNAME=<faktura-username>
FAKTURA_PASSWORD=<faktura-password>
FAKTURA_CLIENT_ID=<faktura-client-id>
FAKTURA_CLIENT_SECRET=<faktura-client-secret>
```

Compose passes these credentials only to the `web` service. The Faktura URLs,
timeout, and optional proxy can also be overridden with the corresponding
`FAKTURA_*` values documented in `.env.production.example`. The backend can
start without these credentials, but Faktura company lookup remains unavailable
until all four credential values are configured.

The production workflow stores the four credential values as base64-encoded
GitHub repository secrets named `FAKTURA_USERNAME_B64`,
`FAKTURA_PASSWORD_B64`, `FAKTURA_CLIENT_ID_B64`, and
`FAKTURA_CLIENT_SECRET_B64`. Each deploy synchronizes them into the server-side
`.env.production` file without logging plaintext values, restricts the file to
mode `0600`, and verifies a live company lookup after the containers start.

## Telegram Sales Reports Bot

Configure these values in the production environment:

```bash
TELEGRAM_REPORTS_BOT_TOKEN=<botfather-token>
TELEGRAM_REPORTS_WEBHOOK_SECRET=<random-secret>
TELEGRAM_REPORTS_WEBHOOK_URL=https://cafe-postcode.uz/api/v1/telegram-reports/webhook/
```

After the new backend version and migrations are live, configure the bot profile,
commands menu, and webhook:

```bash
docker compose --env-file .env.production exec web \
  python manage.py configure_telegram_reports_bot --set-webhook
```

The `telegram_reports` migration creates three Django Q cron schedules in
`Asia/Tashkent`: daily at `00:05`, weekly on Monday at `00:10`, and monthly on
the first day at `00:15`. The `qcluster` service must receive the reports bot
token so scheduled tasks can send messages.

## Health And Monitoring

Public health endpoints:

- `/healthz/`: process liveness
- `/readyz/`: database and Redis readiness

Internal metrics:

- `/metrics`: available to Prometheus on the Docker network, blocked by Nginx

Grafana is exposed on `127.0.0.1:3001` by default. Prometheus is exposed on `127.0.0.1:9090`.

## Verification

Run these before release:

```bash
poetry run python manage.py test --noinput
poetry run python manage.py makemigrations --check --dry-run
DJANGO_PRODUCTION=1 DEBUG=0 SECRET_KEY=<strong-secret> ALLOWED_HOSTS=cafe-postcode.uz DB_ENGINE=postgres REDIS_URL=redis://127.0.0.1:6379/0 poetry run python manage.py check --deploy
docker compose --env-file .env.production config
```

Run load tests from `loadtests/README.md` against a staging or production-like stack.
