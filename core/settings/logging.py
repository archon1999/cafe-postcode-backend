DEFAULT_FORMATTER = '%(asctime)s %(levelname)s %(name)s %(message)s'

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": DEFAULT_FORMATTER,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "apps.accounts": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.orders": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.kitchen": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "common.api": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
