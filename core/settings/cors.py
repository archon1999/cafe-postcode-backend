import os

from corsheaders.defaults import default_headers


def parse_csv_env(name: str) -> list[str]:
    value = os.getenv(name, '')
    return [item.strip() for item in value.split(',') if item.strip()]


CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    'http://localhost:4200',
    'http://localhost:4300',
    'http://localhost:4400',
    'http://localhost:4401',
    'http://localhost:3000',
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://localhost:4173',
    'http://localhost:4174',
    'http://localhost:4175',
    'http://127.0.0.1:4200',
    'http://127.0.0.1:4300',
    'http://127.0.0.1:4400',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'http://127.0.0.1:4173',
    'http://127.0.0.1:4174',
    'http://127.0.0.1:4175',
    'https://cafe-postcode.uz',
    'https://www.cafe-postcode.uz',
    'https://admin.cafe-postcode.uz',
    'https://control.cafe-postcode.uz',
    'https://pos.cafe-postcode.uz',
    'https://dashboard.cafe-postcode.uz',
]
if os.getenv('DJANGO_PRODUCTION', '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
    CORS_ALLOWED_ORIGINS.extend([
        'http://localhost:4500',
        'http://127.0.0.1:4500',
    ])
CORS_ALLOWED_ORIGINS.extend(parse_csv_env('CORS_ALLOWED_ORIGINS'))

CORS_ALLOWED_ORIGIN_REGEXES = []
CORS_ALLOWED_ORIGIN_REGEXES.extend(parse_csv_env('CORS_ALLOWED_ORIGIN_REGEXES'))

CORS_ALLOW_HEADERS = [
    *default_headers,
    'django-language',
    'accept-language',
    'x-language',
    'x-admin-restaurant-id',
    'x-admin-user-activity',
    'x-dashboard-restaurant-id',
    'x-edge-operation-id',
    'x-edge-token',
    'x-device-id',
    'x-device-timestamp',
    'x-device-nonce',
    'x-device-content-sha256',
    'x-device-signature',
    'x-tv-pairing-token',
    'x-tv-token',
]

CORS_EXPOSE_HEADERS = [
    'date',
    'Date',
]

CSRF_TRUSTED_ORIGINS = [
    'https://cafe-postcode.uz',
    'https://*.cafe-postcode.uz',
]
CSRF_TRUSTED_ORIGINS.extend(parse_csv_env('CSRF_TRUSTED_ORIGINS'))

CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
