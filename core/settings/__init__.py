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
from .q_cluster import Q_CLUSTER
from .rest_framework import JSON_CAMEL_CASE, REST_FRAMEWORK
from .templates import TEMPLATES
from .swagger import SWAGGER_SETTINGS

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def load_env_files() -> None:
    env_files = (
        BASE_DIR / 'core' / 'settings' / 'config.env',
        BASE_DIR / '.env',
    )
    for env_file in env_files:
        if env_file.exists():
            dotenv.load_dotenv(env_file, override=True)


load_env_files()


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


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    return float(value.strip())


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
    AWS_S3_CUSTOM_DOMAIN = os.getenv(
        'AWS_S3_CUSTOM_DOMAIN',
        f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com',
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
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

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
