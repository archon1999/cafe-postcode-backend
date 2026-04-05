import os
from pathlib import Path

import dotenv
from class_settings import Settings
from django.utils.translation import gettext_lazy as _

from .auth_password_validators import AUTH_PASSWORD_VALIDATORS
from .caches import CACHES
from .channel_layers import CHANNEL_LAYERS
from .cors import (
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_HEADERS,
    CORS_ALLOWED_ORIGINS,
    CORS_ALLOWED_ORIGIN_REGEXES,
    CORS_EXPOSE_HEADERS,
    CSRF_TRUSTED_ORIGINS,
    CSRF_COOKIE_HTTPONLY,
    SESSION_COOKIE_HTTPONLY
)
from .databases import DATABASES
from .installed_apps import INSTALLED_APPS
from .locale_paths import LOCALE_PATHS
from .logging import LOGGING
from .middleware import MIDDLEWARE
from .rest_framework import REST_FRAMEWORK
from .templates import TEMPLATES
from .swagger import SWAGGER_SETTINGS

BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv.load_dotenv(BASE_DIR / 'core' / 'settings' / 'config.env')


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default

    return [item.strip() for item in value.split(',') if item.strip()]


class CoreSettings(Settings):
    ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', ['localhost', '127.0.0.1', '.cafe-postcode.uz'])
    INTERNAL_IPS = ['127.0.0.1']
    SECRET_KEY = os.getenv('SECRET_KEY') or os.getenv('DJANGO_SECRET_KEY') or 'restaurant-pos-dev-secret'
    DEBUG = env_bool('DEBUG', env_bool('DJANGO_DEBUG', True))
    UNDER_MAINTENANCE = False
    INSTALLED_APPS = INSTALLED_APPS
    MIDDLEWARE = MIDDLEWARE
    ROOT_URLCONF = 'core.urls'
    WSGI_APPLICATION = 'core.wsgi.application'
    ASGI_APPLICATION = 'core.asgi.application'
    SITE_ID = 1
    DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

    AUTH_PASSWORD_VALIDATORS = AUTH_PASSWORD_VALIDATORS
    AUTH_USER_MODEL = 'users.User'
    LOGIN_URL = '/admin/login'
    LOGOUT_URL = '/logout'
    LOGIN_REDIRECT_URL = '/'
    LOGOUT_REDIRECT_URL = '/'

    TEMPLATES = TEMPLATES
    DATABASES = DATABASES

    LOGGING = LOGGING

    DECIMAL_SEPARATOR = '.'

    LANGUAGE_COOKIE_NAME = 'django_language'
    USE_I18N = True
    USE_L10N = True
    USE_TZ = True
    LANGUAGE_CODE = 'uz'
    LANGUAGES = (
        ('uz', _('Uzbek Latin')),
        ('uz-crl', _('Uzbek Cyrillic')),
        ('ru', _('Russian')),
    )
    LOCALE_PATHS = LOCALE_PATHS
    MODELTRANSLATION_DEFAULT_LANGUAGE = 'uz'
    TIME_ZONE = 'Asia/Tashkent'

    STATIC_URL = '/static/'
    STATIC_ROOT = (BASE_DIR / 'staticfiles').as_posix()
    MEDIA_URL = '/media/'
    MEDIA_ROOT = (BASE_DIR / 'media').as_posix()
    STATICFILES_FINDERS = (
        'django.contrib.staticfiles.finders.FileSystemFinder',
        'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    )
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

    REST_FRAMEWORK = REST_FRAMEWORK
    CACHES = CACHES
    CHANNEL_LAYERS = CHANNEL_LAYERS
    SWAGGER_SETTINGS = SWAGGER_SETTINGS

    CORS_ALLOW_CREDENTIALS = CORS_ALLOW_CREDENTIALS
    CORS_ALLOW_HEADERS = CORS_ALLOW_HEADERS
    CORS_ALLOWED_ORIGINS = CORS_ALLOWED_ORIGINS
    CORS_ALLOWED_ORIGIN_REGEXES = CORS_ALLOWED_ORIGIN_REGEXES
    CORS_EXPOSE_HEADERS = CORS_EXPOSE_HEADERS
    CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS
    CSRF_COOKIE_HTTPONLY = CSRF_COOKIE_HTTPONLY
    SESSION_COOKIE_HTTPONLY = SESSION_COOKIE_HTTPONLY
