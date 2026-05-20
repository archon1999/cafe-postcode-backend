import os
from pathlib import Path

import dotenv
from django.core.exceptions import ImproperlyConfigured

dotenv.load_dotenv(Path(__file__).parent / 'config.env')

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DATA_DIR = BASE_DIR / 'var'

db_engine = os.getenv('DB_ENGINE', '').lower()
use_postgres = db_engine in {'postgres', 'postgresql'} or os.getenv('USE_POSTGRES') == '1'
debug_mode = (os.getenv('DEBUG') or os.getenv('DJANGO_DEBUG') or '0').strip().lower() in {'1', 'true', 'yes', 'on'}
production_mode = os.getenv('DJANGO_PRODUCTION', '').strip().lower() in {'1', 'true', 'yes', 'on'}
allow_sqlite_fallback = debug_mode or os.getenv('ALLOW_SQLITE_FALLBACK') == '1'

if use_postgres:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql_psycopg2',
            'NAME': os.getenv('DB_NAME'),
            'USER': os.getenv('DB_USER'),
            'PASSWORD': os.getenv('DB_PASSWORD'),
            'HOST': os.getenv('DB_HOST'),
            'PORT': os.getenv('DB_PORT'),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    if production_mode or not allow_sqlite_fallback:
        raise ImproperlyConfigured(
            'SQLite fallback is only allowed in local development. Set DB_ENGINE=postgres or ALLOW_SQLITE_FALLBACK=1.'
        )
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': Path(os.getenv('SQLITE_PATH') or (LOCAL_DATA_DIR / 'db.sqlite3')),
            'OPTIONS': {
                'timeout': float(os.getenv('SQLITE_TIMEOUT_SECONDS', '20')),
            },
        }
    }
