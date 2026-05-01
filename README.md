# Cafe Postcode Backend

This directory contains the Django backend for the cafe-postcode.uz restaurant POS platform. The codebase is organized by domain apps under `apps/`, with shared infrastructure in `core/` and reusable helpers in `common/`.

## Stack

- Python 3.12
- Django 4.2
- Django REST Framework
- Poetry for dependency management
- SQLite by default for local development
- Optional PostgreSQL via environment variables

## Project layout

- `apps/` domain apps such as `accounts`, `admin`, `catalog`, `floor`, `orders`, and `reports`
- `core/` Django settings, URL configuration, ASGI/WSGI entrypoints, and API documentation setup
- `common/` shared API helpers, constants, exceptions, model mixins, and utility modules
- `manage.py` standard Django management entrypoint

## Configuration

Settings are loaded from `core/settings/config.env` and process environment variables.

Common variables:

- `SECRET_KEY` or `DJANGO_SECRET_KEY`
- `DEBUG` or `DJANGO_DEBUG`
- `ALLOWED_HOSTS`
- `DB_ENGINE`
- `USE_POSTGRES`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`

If `DB_ENGINE=postgres` or `USE_POSTGRES=1`, PostgreSQL is used. Otherwise the project falls back to local SQLite.

## Local setup

```bash
poetry install
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

## Useful commands

```bash
poetry run python manage.py check
poetry run python manage.py test
poetry run python manage.py makemigrations --check
```

## Production

Docker Compose production deployment, monitoring, and load testing instructions are in `DEPLOYMENT.md` and `loadtests/README.md`.

## API docs

- Swagger UI: `/api/swagger/`
- ReDoc: `/api/redoc/`
- OpenAPI schema: `/api/swagger.json` or `/api/swagger.yaml`

In production these routes are available only when `ENABLE_API_DOCS=1`.
