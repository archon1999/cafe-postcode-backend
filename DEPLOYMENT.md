# Backend Deployment

## Docker Compose Production Stack

Production is prepared for Docker Compose with:

- `web`: Django + Gunicorn on `0.0.0.0:8888`
- `qcluster`: Django Q worker
- `postgres`: PostgreSQL
- `redis`: cache, channel layer, and Django Q broker
- `nginx`: public reverse proxy; `/metrics` is blocked externally
- `prometheus`, `grafana`, `postgres-exporter`, `redis-exporter`: monitoring

Create an env file from the example and replace every placeholder secret:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production up -d --build
```

The `web` service runs migrations and `collectstatic` before Gunicorn starts. Prometheus scrapes Django metrics directly on the internal Docker network at `web:8888/metrics`.

By default Docker Nginx binds to `127.0.0.1:8880` so it can run behind the host Certbot/TLS Nginx. The host-level `cafe-postcode` Nginx config is stored at `nginx/cafe-postcode.uz.conf` and included by the host Nginx service.

## Required Production Settings

`DJANGO_PRODUCTION=1` enforces:

- `DEBUG=0`
- explicit `ALLOWED_HOSTS`
- strong `SECRET_KEY`
- PostgreSQL via `DB_ENGINE=postgres`
- `REDIS_URL`

The production Compose defaults expect TLS to be terminated before or at Nginx:

```bash
SECURE_SSL_REDIRECT=1
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
```

For local HTTP-only smoke tests, temporarily set those three values to `0` in `.env.production`.

Only enable API docs intentionally:

```bash
ENABLE_API_DOCS=1
```

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
