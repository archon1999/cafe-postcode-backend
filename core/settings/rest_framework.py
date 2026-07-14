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
        'pin_login': '20/min',
        'submit': '10/min',
        'agent_enrollment': '10/min',
    }
}

AUTH_SESSION_TTL_SECONDS = {
    # Keep login/password and POS PIN sessions active for a full day by default.
    'admin': int(os.getenv('ADMIN_AUTH_SESSION_TTL_SECONDS', str(24 * 60 * 60))),
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
