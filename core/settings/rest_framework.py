from common.constants import DEFAULT_PAGE_SIZE

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'common.api.paginations.Pagination',
    'PAGE_SIZE': DEFAULT_PAGE_SIZE,
    'EXCEPTION_HANDLER': 'common.api.exception_handler.custom_exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
        'djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer',
    ),
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
    }
}

JSON_CAMEL_CASE = {
    'JSON_UNDERSCOREIZE': {
        'no_underscore_before_number': False,
        'ignore_fields': ('mxik_payload',),
        'ignore_keys': None,
    },
}
