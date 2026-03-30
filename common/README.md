# Common

`common/` contains shared pieces that are reused across multiple apps.

## API helpers

`common/api/` contains project-level DRF utilities:

- `authentication.py` custom basic-auth behavior
- `exception_handler.py` shared API exception formatting
- `paginations.py` shared pagination classes
- `permissions.py` reusable DRF permission classes
- `query_params.py` reusable query-string parsing helpers
- `renderers.py`, `routers.py`, `scopes.py`, `serializers.py`, `throttling.py`, `views.py`

## Shared modules

- `constants.py` shared API and pagination constants
- `exceptions.py` shared API exception classes
- `indexes.py` reusable Django model index helpers
- `models.py` base abstract models with UUID and timestamp fields
- `admin.py` translation-admin helper for Django admin integrations
- `django_init.py` alternative bootstrap entrypoint for Django management execution

## Utilities

`common/utils/` currently provides:

- `data.py`
- `date.py`
- `language.py`
