# Core

`core/` contains the Django project wiring: settings, URL routing, and deployment entrypoints.

## Main files

- `settings/__init__.py` loads the active settings class
- `urls.py` defines admin, API, and documentation routes
- `asgi.py` and `wsgi.py` expose deployment entrypoints
- `yasg.py` configures Swagger and ReDoc schema generation

## Active settings modules

- `auth_password_validators.py`
- `caches.py`
- `channel_layers.py`
- `cors.py`
- `databases.py`
- `installed_apps.py`
- `locale_paths.py`
- `logging.py`
- `middleware.py`
- `rest_framework.py`
- `swagger.py`
- `templates.py`

These modules are imported by `settings/__init__.py` and are part of the current runtime configuration.

## Background jobs

- `settings/q_cluster.py` is loaded by default from `settings/__init__.py`
- `django_q` is part of the active runtime and is used for restaurant subscription expiry checks

## Notes

- SQLite is the default local database
- PostgreSQL is enabled through environment variables
- Channels currently use the in-memory layer configured in `settings/channel_layers.py`
