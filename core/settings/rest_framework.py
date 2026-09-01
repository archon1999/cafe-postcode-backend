import os

from common.constants import DEFAULT_PAGE_SIZE


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


DEBUG = env_bool('DEBUG', env_bool('DJANGO_DEBUG', True))
ENABLE_BROWSABLE_API = env_bool('ENABLE_BROWSABLE_API', DEBUG)

DEFAULT_RENDERER_CLASSES = (
    'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
)
if ENABLE_BROWSABLE_API:
    DEFAULT_RENDERER_CLASSES = DEFAULT_RENDERER_CLASSES + (
        'djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer',
    )

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'common.api.paginations.Pagination',
    'PAGE_SIZE': DEFAULT_PAGE_SIZE,
    'EXCEPTION_HANDLER': 'common.api.exception_handler.custom_exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'common.api.authentication.ExpiringSessionTokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_RENDERER_CLASSES': DEFAULT_RENDERER_CLASSES,
    'DEFAULT_PARSER_CLASSES': (
        'djangorestframework_camel_case.parser.CamelCaseFormParser',
        'djangorestframework_camel_case.parser.CamelCaseMultiPartParser',
        'djangorestframework_camel_case.parser.CamelCaseJSONParser',
    ),
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '120/min',
        'login': '10/min',
        'pin_login': '10/min',
        'pin_device': '5/min',
        'submit': '10/min',
        'device_pairing': '6/min',
        'device_migration': '30/min',
        'local_agent': '600/min',
        'restaurant_code_migration': '10/min',
        'control_pairing_resolve': '30/min',
        'control_pairing_decision': '60/min',
        'catalog_translation': '30/min',
    }
}

AUTH_SESSION_TTL_SECONDS = {
    # Admin access credentials are deliberately short-lived; the browser uses
    # the rotating HttpOnly refresh family for continuity.
    'admin': int(os.getenv('ADMIN_AUTH_SESSION_TTL_SECONDS', str(15 * 60))),
    'pos': int(os.getenv('POS_AUTH_SESSION_TTL_SECONDS', str(24 * 60 * 60))),
    'dashboard': int(os.getenv('DASHBOARD_AUTH_SESSION_TTL_SECONDS', str(24 * 60 * 60))),
}

JSON_CAMEL_CASE = {
    'JSON_UNDERSCOREIZE': {
        'no_underscore_before_number': False,
        'ignore_fields': ('mxik_payload',),
        'ignore_keys': None,
    },
}
