import os


DEFAULT_FORMATTER = '%(asctime)s %(levelname)s %(name)s %(message)s'
JSON_FORMATTER = (
    '%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(user_id)s '
    '%(restaurant_id)s %(method)s %(path)s %(status_code)s %(latency_ms)s'
)

CONSOLE_FORMATTER = 'standard' if os.getenv('LOG_FORMAT', 'json').strip().lower() == 'text' else 'json'
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').strip().upper() or 'INFO'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'request_context': {
            '()': 'core.observability.RequestContextFilter',
        },
        'sensitive_data': {
            '()': 'core.observability.SensitiveLogFilter',
        },
    },
    'formatters': {
        'standard': {
            'format': DEFAULT_FORMATTER,
        },
        'json': {
            'class': 'pythonjsonlogger.json.JsonFormatter',
            'format': JSON_FORMATTER,
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': CONSOLE_FORMATTER,
            'filters': ['request_context', 'sensitive_data'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'common': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        # Telegram requires the bot token in the request URL. httpx logs full URLs
        # at INFO level, so keep transport logs above INFO to avoid leaking tokens.
        'httpx': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
