import ipaddress
import os
from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path

import dotenv
from class_settings import Settings
from cryptography.fernet import Fernet
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
ADMIN_MFA_FERNET_KEYS_VALUE = env_list('ADMIN_MFA_FERNET_KEYS', [])
ADMIN_MFA_REQUIRED_VALUE = env_bool('ADMIN_MFA_REQUIRED', False)
INTEGRATION_FERNET_KEYS_VALUE = env_list('INTEGRATION_FERNET_KEYS', [])
DJANGO_ADMIN_ENABLED_VALUE = env_bool('DJANGO_ADMIN_ENABLED', not PRODUCTION_MODE)
DJANGO_ADMIN_ALLOWED_CIDRS_VALUE = env_list('DJANGO_ADMIN_ALLOWED_CIDRS', [])
DJANGO_ADMIN_TRUSTED_PROXY_CIDRS_VALUE = env_list('DJANGO_ADMIN_TRUSTED_PROXY_CIDRS', [])
CLIENT_IP_TRUSTED_PROXY_CIDRS_VALUE = env_list('CLIENT_IP_TRUSTED_PROXY_CIDRS', ['127.0.0.1/32'])
DEVICE_POS_PROOF_REQUIRED_VALUE = env_bool('DEVICE_POS_PROOF_REQUIRED', PRODUCTION_MODE)
DEVICE_LEGACY_POS_MIGRATION_ENABLED_VALUE = env_bool('DEVICE_LEGACY_POS_MIGRATION_ENABLED', False)
DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED_VALUE = env_bool('DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED', False)
DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED_VALUE = env_bool(
    'DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED',
    False,
)
DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED_VALUE = env_bool(
    'DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED',
    not PRODUCTION_MODE,
)
DEVICE_LEGACY_TV_PAIRING_ENABLED_VALUE = env_bool('DEVICE_LEGACY_TV_PAIRING_ENABLED', not PRODUCTION_MODE)
DEVICE_LEGACY_TV_MIGRATION_ENABLED_VALUE = env_bool('DEVICE_LEGACY_TV_MIGRATION_ENABLED', not PRODUCTION_MODE)
DEVICE_LEGACY_MIGRATION_STARTED_AT_VALUE = os.getenv('DEVICE_LEGACY_MIGRATION_STARTED_AT', '').strip()
DEVICE_LEGACY_MIGRATION_DEADLINE_VALUE = os.getenv('DEVICE_LEGACY_MIGRATION_DEADLINE', '').strip()


def parse_device_migration_timestamp(value: str, *, setting_name: str):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ImproperlyConfigured(
            f'{setting_name} must be an ISO-8601 timestamp with a timezone.'
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ImproperlyConfigured(
            f'{setting_name} must include an explicit timezone.'
        )
    return parsed.astimezone(datetime_timezone.utc)


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

    if not DEVICE_POS_PROOF_REQUIRED_VALUE:
        raise ImproperlyConfigured(
            'DEVICE_POS_PROOF_REQUIRED must remain enabled in production; '
            'trusted terminals migrate through the attested migration endpoint.'
        )
    if DEBUG_VALUE:
        raise ImproperlyConfigured('DEBUG must be disabled when DJANGO_PRODUCTION=1.')
    if ENABLE_API_DOCS_VALUE:
        raise ImproperlyConfigured('ENABLE_API_DOCS must be disabled when DJANGO_PRODUCTION=1.')
    if env_bool('DISABLE_CSRF_CHECKS', False):
        raise ImproperlyConfigured('DISABLE_CSRF_CHECKS must remain disabled in production.')
    if not os.getenv('ALLOWED_HOSTS'):
        raise ImproperlyConfigured('ALLOWED_HOSTS must be set explicitly when DJANGO_PRODUCTION=1.')
    if is_weak_secret_key(SECRET_KEY_VALUE):
        raise ImproperlyConfigured('SECRET_KEY must be long, random, and unique when DJANGO_PRODUCTION=1.')
    if not os.getenv('REDIS_URL'):
        raise ImproperlyConfigured('REDIS_URL is required when DJANGO_PRODUCTION=1.')
    if os.getenv('USE_POSTGRES') != '1' and os.getenv('DB_ENGINE', '').lower() not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('PostgreSQL is required when DJANGO_PRODUCTION=1.')
    if not env_bool('DJANGO_MIGRATION_PROCESS', False):
        runtime_db_user = os.getenv('DB_USER', '').strip()
        admin_db_user = os.getenv('DB_ADMIN_USER', '').strip()
        if not runtime_db_user or not admin_db_user or runtime_db_user == admin_db_user:
            raise ImproperlyConfigured(
                'Production runtime containers require distinct DB_USER and DB_ADMIN_USER roles.'
            )
    if ADMIN_MFA_REQUIRED_VALUE and not ADMIN_MFA_FERNET_KEYS_VALUE:
        raise ImproperlyConfigured('ADMIN_MFA_FERNET_KEYS is required when DJANGO_PRODUCTION=1.')
    for key in ADMIN_MFA_FERNET_KEYS_VALUE:
        try:
            Fernet(key.encode('ascii'))
        except (TypeError, ValueError) as error:
            raise ImproperlyConfigured('Every ADMIN_MFA_FERNET_KEYS value must be a valid Fernet key.') from error
    if not INTEGRATION_FERNET_KEYS_VALUE:
        raise ImproperlyConfigured('INTEGRATION_FERNET_KEYS is required when DJANGO_PRODUCTION=1.')
    for key in INTEGRATION_FERNET_KEYS_VALUE:
        try:
            Fernet(key.encode('ascii'))
        except (TypeError, ValueError) as error:
            raise ImproperlyConfigured('Every INTEGRATION_FERNET_KEYS value must be a valid Fernet key.') from error
    for name, values in (
        ('DJANGO_ADMIN_ALLOWED_CIDRS', DJANGO_ADMIN_ALLOWED_CIDRS_VALUE),
        ('DJANGO_ADMIN_TRUSTED_PROXY_CIDRS', DJANGO_ADMIN_TRUSTED_PROXY_CIDRS_VALUE),
        ('CLIENT_IP_TRUSTED_PROXY_CIDRS', CLIENT_IP_TRUSTED_PROXY_CIDRS_VALUE),
    ):
        try:
            for value in values:
                ipaddress.ip_network(value, strict=False)
        except ValueError as error:
            raise ImproperlyConfigured(f'{name} contains an invalid network.') from error
    if DJANGO_ADMIN_ENABLED_VALUE and not DJANGO_ADMIN_ALLOWED_CIDRS_VALUE:
        raise ImproperlyConfigured(
            'DJANGO_ADMIN_ALLOWED_CIDRS is required when Django admin is enabled in production.'
        )
    if not CLIENT_IP_TRUSTED_PROXY_CIDRS_VALUE:
        raise ImproperlyConfigured('CLIENT_IP_TRUSTED_PROXY_CIDRS is required in production.')
    if os.getenv('TELEGRAM_REPORTS_BOT_TOKEN', '').strip():
        if not os.getenv('TELEGRAM_REPORTS_WEBHOOK_SECRET', '').strip():
            raise ImproperlyConfigured(
                'TELEGRAM_REPORTS_WEBHOOK_SECRET is required when the Telegram reports bot is enabled.'
            )
        if not os.getenv('TELEGRAM_REPORTS_BOT_USERNAME', '').strip().lstrip('@'):
            raise ImproperlyConfigured(
                'TELEGRAM_REPORTS_BOT_USERNAME is required when the Telegram reports bot is enabled.'
            )
    legacy_window_requested = (
        not DEVICE_POS_PROOF_REQUIRED_VALUE
        or DEVICE_LEGACY_POS_MIGRATION_ENABLED_VALUE
        or DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED_VALUE
        or DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED_VALUE
        or DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED_VALUE
        or DEVICE_LEGACY_TV_PAIRING_ENABLED_VALUE
        or DEVICE_LEGACY_TV_MIGRATION_ENABLED_VALUE
    )
    if legacy_window_requested:
        if not DEVICE_LEGACY_MIGRATION_STARTED_AT_VALUE:
            raise ImproperlyConfigured(
                'DEVICE_LEGACY_MIGRATION_STARTED_AT is required while any legacy device path is enabled.'
            )
        if not DEVICE_LEGACY_MIGRATION_DEADLINE_VALUE:
            raise ImproperlyConfigured(
                'DEVICE_LEGACY_MIGRATION_DEADLINE is required while any legacy device path is enabled.'
            )
        started_at = parse_device_migration_timestamp(
            DEVICE_LEGACY_MIGRATION_STARTED_AT_VALUE,
            setting_name='DEVICE_LEGACY_MIGRATION_STARTED_AT',
        )
        deadline = parse_device_migration_timestamp(
            DEVICE_LEGACY_MIGRATION_DEADLINE_VALUE,
            setting_name='DEVICE_LEGACY_MIGRATION_DEADLINE',
        )
        if deadline <= started_at:
            raise ImproperlyConfigured(
                'DEVICE_LEGACY_MIGRATION_DEADLINE must be later than DEVICE_LEGACY_MIGRATION_STARTED_AT.'
            )
        if deadline - started_at > timedelta(days=31):
            raise ImproperlyConfigured(
                'The legacy device migration window cannot exceed 31 days.'
            )


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
from .rest_framework import AUTH_SESSION_TTL_SECONDS, JSON_CAMEL_CASE, REST_FRAMEWORK
from .swagger import SWAGGER_SETTINGS
from .templates import TEMPLATES


class CoreSettings(Settings):
    ALLOWED_HOSTS = ALLOWED_HOSTS_VALUE
    INTERNAL_IPS = ['127.0.0.1']
    SECRET_KEY = SECRET_KEY_VALUE
    DEBUG = DEBUG_VALUE
    DJANGO_PRODUCTION = PRODUCTION_MODE
    CLIENT_IP_TRUSTED_PROXY_CIDRS = CLIENT_IP_TRUSTED_PROXY_CIDRS_VALUE
    ENABLE_API_DOCS = ENABLE_API_DOCS_VALUE
    DISABLE_CSRF_CHECKS = env_bool('DISABLE_CSRF_CHECKS', DEBUG_VALUE and not PRODUCTION_MODE)
    DEVICE_PAIRING_CLAIM_BASE_URL = os.getenv(
        'DEVICE_PAIRING_CLAIM_BASE_URL',
        'https://control.cafe-postcode.uz/pair',
    ).strip()
    DEVICE_LEGACY_POS_MIGRATION_ENABLED = DEVICE_LEGACY_POS_MIGRATION_ENABLED_VALUE
    DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED = DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED_VALUE
    DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED = DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED_VALUE
    DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED = DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED_VALUE
    DEVICE_LEGACY_LOCAL_AGENT_RECOVERY_BINDINGS = os.getenv(
        'DEVICE_LEGACY_LOCAL_AGENT_RECOVERY_BINDINGS', ''
    ).strip()
    DEVICE_LEGACY_MIGRATION_STARTED_AT = DEVICE_LEGACY_MIGRATION_STARTED_AT_VALUE
    DEVICE_LEGACY_MIGRATION_DEADLINE = DEVICE_LEGACY_MIGRATION_DEADLINE_VALUE
    DEVICE_LEGACY_TV_PAIRING_ENABLED = DEVICE_LEGACY_TV_PAIRING_ENABLED_VALUE
    DEVICE_LEGACY_TV_MIGRATION_ENABLED = DEVICE_LEGACY_TV_MIGRATION_ENABLED_VALUE
    DEVICE_POS_PROOF_REQUIRED = DEVICE_POS_PROOF_REQUIRED_VALUE
    ADMIN_MFA_REQUIRED = ADMIN_MFA_REQUIRED_VALUE
    SECURITY_EVENT_RETENTION_DAYS = env_int('SECURITY_EVENT_RETENTION_DAYS', 180)
    DEVICE_PAIRING_RETENTION_DAYS = env_int('DEVICE_PAIRING_RETENTION_DAYS', 30)
    ADMIN_AUTH_ALLOWED_ORIGINS = list(
        dict.fromkeys(
            [
                *env_list(
                    'ADMIN_AUTH_ALLOWED_ORIGINS',
                    ['https://admin.cafe-postcode.uz', 'https://control.cafe-postcode.uz']
                    if PRODUCTION_MODE
                    else [
                        'http://localhost:4200',
                        'http://localhost:4500',
                        'http://localhost:5173',
                        'http://127.0.0.1:4200',
                        'http://127.0.0.1:4500',
                        'http://127.0.0.1:5173',
                    ],
                ),
                'https://admin.cafe-postcode.uz',
                'https://control.cafe-postcode.uz',
            ]
        )
    )
    ADMIN_REFRESH_COOKIE_NAME = '__Host-cafe_admin_refresh'
    ADMIN_REFRESH_COOKIE_SECURE = True
    ADMIN_REFRESH_COOKIE_SAMESITE = 'Strict'
    ADMIN_REFRESH_COOKIE_PATH = '/'
    ADMIN_REFRESH_ABSOLUTE_TTL_SECONDS = env_int('ADMIN_REFRESH_ABSOLUTE_TTL_SECONDS', 30 * 24 * 60 * 60)
    ADMIN_REFRESH_RACE_GRACE_SECONDS = env_int('ADMIN_REFRESH_RACE_GRACE_SECONDS', 5)
    # Zero disables the automatic idle lock. Explicit lock/logout flows remain available.
    ADMIN_IDLE_LOCK_SECONDS = env_int('ADMIN_IDLE_LOCK_SECONDS', 0)
    ADMIN_MFA_CHALLENGE_TTL_SECONDS = env_int('ADMIN_MFA_CHALLENGE_TTL_SECONDS', 5 * 60)
    ADMIN_MFA_MAX_ATTEMPTS = env_int('ADMIN_MFA_MAX_ATTEMPTS', 5)
    ADMIN_LOGIN_LOCKOUT_SECONDS = env_int('ADMIN_LOGIN_LOCKOUT_SECONDS', 15 * 60)
    ADMIN_LOGIN_MAX_FAILURES = env_int('ADMIN_LOGIN_MAX_FAILURES', 5)
    ADMIN_MFA_FERNET_KEYS = ADMIN_MFA_FERNET_KEYS_VALUE
    INTEGRATION_FERNET_KEYS = INTEGRATION_FERNET_KEYS_VALUE
    DJANGO_ADMIN_ENABLED = DJANGO_ADMIN_ENABLED_VALUE
    DJANGO_ADMIN_ALLOWED_CIDRS = DJANGO_ADMIN_ALLOWED_CIDRS_VALUE
    DJANGO_ADMIN_TRUSTED_PROXY_CIDRS = DJANGO_ADMIN_TRUSTED_PROXY_CIDRS_VALUE
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

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    TELEGRAM_LEADS_CHAT_ID = os.getenv('TELEGRAM_LEADS_CHAT_ID', '').strip()
    TELEGRAM_TIMEOUT = env_float('TELEGRAM_TIMEOUT', 10.0)
    TELEGRAM_PROXY_URL = os.getenv('TELEGRAM_PROXY_URL', '').strip()

    YANDEX_TRANSLATE_API_KEY = os.getenv('YANDEX_TRANSLATE_API_KEY', '').strip()
    YANDEX_TRANSLATE_FOLDER_ID = os.getenv('YANDEX_TRANSLATE_FOLDER_ID', '').strip()
    YANDEX_TRANSLATE_TIMEOUT = env_float('YANDEX_TRANSLATE_TIMEOUT', 10.0)
    TELEGRAM_REPORTS_BOT_TOKEN = os.getenv('TELEGRAM_REPORTS_BOT_TOKEN', '').strip()
    TELEGRAM_REPORTS_BOT_USERNAME = os.getenv('TELEGRAM_REPORTS_BOT_USERNAME', '').strip().lstrip('@')
    TELEGRAM_REPORTS_WEBHOOK_SECRET = os.getenv('TELEGRAM_REPORTS_WEBHOOK_SECRET', '').strip()
    TELEGRAM_REPORTS_WEBHOOK_URL = os.getenv('TELEGRAM_REPORTS_WEBHOOK_URL', '').strip()

    LOCAL_AGENT_RELEASE_MANIFEST_URL = os.getenv(
        'LOCAL_AGENT_RELEASE_MANIFEST_URL',
        'https://admin.cafe-postcode.uz/downloads/local-agent-release.json',
    ).strip()

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
    AUTH_SESSION_TTL_SECONDS = AUTH_SESSION_TTL_SECONDS
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
