import os


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
]
CORS_ALLOWED_ORIGINS.extend(parse_csv_env('CORS_ALLOWED_ORIGINS'))

CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https://([a-z0-9-]+\.)?cafe-postcode\.uz$',
]
CORS_ALLOWED_ORIGIN_REGEXES.extend(parse_csv_env('CORS_ALLOWED_ORIGIN_REGEXES'))

CORS_ALLOW_HEADERS = [
    'django-language',
    'accept-language',
    'x-language',
    "accept",
    'access-control-allow-origin',
    'access-control-allow-credentials',
    "accept-encoding",
    "authorization",
    "content-type",
    "set-cookie",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-admin-restaurant-id",
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
