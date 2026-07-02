import os
from pathlib import Path

import dotenv
from class_settings import Settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def load_env_files() -> None:
    env_files = (
        BASE_DIR / 'core' / 'settings' / 'config.env',
        BASE_DIR / '.env',
    )
    for env_file in env_files:
        if env_file.exists():
            dotenv.load_dotenv(env_file, override=False)


load_env_files()


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    return int(value.strip())


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default

    return [item.strip() for item in value.split(',') if item.strip()]


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    return float(value.strip())


PRODUCTION_MODE = env_bool('DJANGO_PRODUCTION', False)
DEBUG_VALUE = False if PRODUCTION_MODE else env_bool('DEBUG', env_bool('DJANGO_DEBUG', True))
ALLOWED_HOSTS_VALUE = env_list('ALLOWED_HOSTS', ['localhost', '127.0.0.1', '.cafe-postcode.uz'])
SECRET_KEY_VALUE = os.getenv('SECRET_KEY') or os.getenv('DJANGO_SECRET_KEY') or 'restaurant-pos-dev-secret'
ENABLE_API_DOCS_VALUE = env_bool('ENABLE_API_DOCS', DEBUG_VALUE)


def is_weak_secret_key(value: str) -> bool:
    return (
        not value
        or value == 'restaurant-pos-dev-secret'
        or value.startswith('django-insecure-')
        or len(value) < 50
        or len(set(value)) < 5
    )


def validate_production_environment() -> None:
    if not PRODUCTION_MODE:
        return

    if DEBUG_VALUE:
        raise ImproperlyConfigured('DEBUG must be disabled when DJANGO_PRODUCTION=1.')
    if not os.getenv('ALLOWED_HOSTS'):
        raise ImproperlyConfigured('ALLOWED_HOSTS must be set explicitly when DJANGO_PRODUCTION=1.')
    if is_weak_secret_key(SECRET_KEY_VALUE):
        raise ImproperlyConfigured('SECRET_KEY must be long, random, and unique when DJANGO_PRODUCTION=1.')
    if not os.getenv('REDIS_URL'):
        raise ImproperlyConfigured('REDIS_URL is required when DJANGO_PRODUCTION=1.')
    if os.getenv('USE_POSTGRES') != '1' and os.getenv('DB_ENGINE', '').lower() not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('PostgreSQL is required when DJANGO_PRODUCTION=1.')


validate_production_environment()

from .auth_password_validators import AUTH_PASSWORD_VALIDATORS
from .caches import CACHES
from .channel_layers import CHANNEL_LAYERS
from .cors import (
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_HEADERS,
    CORS_ALLOWED_ORIGINS,
    CORS_ALLOWED_ORIGIN_REGEXES,
    CORS_EXPOSE_HEADERS,
    CSRF_COOKIE_HTTPONLY,
    CSRF_TRUSTED_ORIGINS,
    SESSION_COOKIE_HTTPONLY,
)
from .databases import DATABASES
from .installed_apps import INSTALLED_APPS
from .locale_paths import LOCALE_PATHS
from .logging import LOGGING
from .middleware import MIDDLEWARE
from .q_cluster import Q_CLUSTER
from .rest_framework import JSON_CAMEL_CASE, REST_FRAMEWORK
from .swagger import SWAGGER_SETTINGS
from .templates import TEMPLATES


class CoreSettings(Settings):
    ALLOWED_HOSTS = ALLOWED_HOSTS_VALUE
    INTERNAL_IPS = ['127.0.0.1']
    SECRET_KEY = SECRET_KEY_VALUE
    DEBUG = DEBUG_VALUE
    DJANGO_PRODUCTION = PRODUCTION_MODE
    ENABLE_API_DOCS = ENABLE_API_DOCS_VALUE
    DISABLE_CSRF_CHECKS = env_bool('DISABLE_CSRF_CHECKS', DEBUG_VALUE and not PRODUCTION_MODE)
    UNDER_MAINTENANCE = False
    INSTALLED_APPS = INSTALLED_APPS
    MIDDLEWARE = MIDDLEWARE
    ROOT_URLCONF = 'core.urls'
    WSGI_APPLICATION = 'core.wsgi.application'
    ASGI_APPLICATION = 'core.asgi.application'
    SITE_ID = 1
    DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', PRODUCTION_MODE)
    SECURE_REDIRECT_EXEMPT = env_list('SECURE_REDIRECT_EXEMPT', [r'^healthz/$', r'^readyz/$', r'^metrics$'])
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = env_bool('USE_X_FORWARDED_HOST', PRODUCTION_MODE)
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', PRODUCTION_MODE)
    CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', PRODUCTION_MODE)
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax').strip()
    CSRF_COOKIE_SAMESITE = os.getenv('CSRF_COOKIE_SAMESITE', 'Lax').strip()
    SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000 if PRODUCTION_MODE else 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', PRODUCTION_MODE)
    SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', PRODUCTION_MODE)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = os.getenv('SECURE_REFERRER_POLICY', 'strict-origin-when-cross-origin').strip()
    SECURE_CROSS_ORIGIN_OPENER_POLICY = os.getenv('SECURE_CROSS_ORIGIN_OPENER_POLICY', 'same-origin').strip()

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

    FAKTURA_TOKEN_URL = os.getenv('FAKTURA_TOKEN_URL', 'https://account.faktura.uz/token').strip()
    FAKTURA_API_BASE_URL = os.getenv('FAKTURA_API_BASE_URL', 'https://api.faktura.uz').strip()
    FAKTURA_USERNAME = os.getenv('FAKTURA_USERNAME', '').strip()
    FAKTURA_PASSWORD = os.getenv('FAKTURA_PASSWORD', '').strip()
    FAKTURA_CLIENT_ID = os.getenv('FAKTURA_CLIENT_ID', '').strip()
    FAKTURA_CLIENT_SECRET = os.getenv('FAKTURA_CLIENT_SECRET', '').strip()
    FAKTURA_TIMEOUT = env_float('FAKTURA_TIMEOUT', 10.0)
    FAKTURA_PROXY_URL = os.getenv('FAKTURA_PROXY_URL', '').strip()

    QZ_TRAY_CERTIFICATE_PEM = os.getenv('QZ_TRAY_CERTIFICATE_PEM', '').replace('\\n', '\n').strip()
    QZ_TRAY_PRIVATE_KEY_PEM = os.getenv('QZ_TRAY_PRIVATE_KEY_PEM', '').replace('\\n', '\n').strip()
    QZ_TRAY_CERTIFICATE_PATH = os.getenv('QZ_TRAY_CERTIFICATE_PATH', '').strip()
    QZ_TRAY_PRIVATE_KEY_PATH = os.getenv('QZ_TRAY_PRIVATE_KEY_PATH', '').strip()
    QZ_TRAY_PRIVATE_KEY_PASSWORD = os.getenv('QZ_TRAY_PRIVATE_KEY_PASSWORD', '').strip()

    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '').strip()
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '').strip()
    AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', 'cpython').strip()
    AWS_S3_MEDIA_PREFIX = os.getenv('AWS_S3_MEDIA_PREFIX', 'media/cafe-postcode').strip().strip('/')
    AWS_DEFAULT_ACL = os.getenv('AWS_DEFAULT_ACL', 'public-read').strip()
    AWS_S3_CUSTOM_DOMAIN = (
        os.getenv('AWS_S3_CUSTOM_DOMAIN') or f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
    ).strip()
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=31536000',
    }

    STATIC_URL = '/static/'
    STATIC_ROOT = (BASE_DIR / 'staticfiles').as_posix()
    MEDIA_URL = '/media/'
    MEDIA_ROOT = (BASE_DIR / 'media').as_posix()
    STATICFILES_FINDERS = (
        'django.contrib.staticfiles.finders.FileSystemFinder',
        'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    )
    STATICFILES_STORAGE = os.getenv(
        'STATICFILES_STORAGE',
        'whitenoise.storage.CompressedManifestStaticFilesStorage'
        if PRODUCTION_MODE
        else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    ).strip()

    REST_FRAMEWORK = REST_FRAMEWORK
    JSON_CAMEL_CASE = JSON_CAMEL_CASE
    CACHES = CACHES
    CHANNEL_LAYERS = CHANNEL_LAYERS
    Q_CLUSTER = Q_CLUSTER
    SWAGGER_SETTINGS = SWAGGER_SETTINGS

    CORS_ALLOW_CREDENTIALS = CORS_ALLOW_CREDENTIALS
    CORS_ALLOW_HEADERS = CORS_ALLOW_HEADERS
    CORS_ALLOWED_ORIGINS = CORS_ALLOWED_ORIGINS
    CORS_ALLOWED_ORIGIN_REGEXES = CORS_ALLOWED_ORIGIN_REGEXES
    CORS_EXPOSE_HEADERS = CORS_EXPOSE_HEADERS
    CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS
    CSRF_COOKIE_HTTPONLY = CSRF_COOKIE_HTTPONLY
    SESSION_COOKIE_HTTPONLY = SESSION_COOKIE_HTTPONLY
