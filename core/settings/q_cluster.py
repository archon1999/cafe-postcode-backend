import os
from urllib.parse import unquote, urlparse


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value.strip())


def redis_config_from_url(redis_url: str) -> dict:
    parsed = urlparse(redis_url)
    db_path = (parsed.path or '/0').lstrip('/') or '0'
    config = {
        'host': parsed.hostname or '127.0.0.1',
        'port': parsed.port or 6379,
        'db': int(db_path),
    }
    if parsed.username:
        config['username'] = unquote(parsed.username)
    if parsed.password:
        config['password'] = unquote(parsed.password)
    if parsed.scheme == 'rediss':
        config['ssl'] = True
    return config


REDIS_URL = os.getenv('REDIS_URL', '').strip()

Q_CLUSTER = {
    'name': os.getenv('Q_CLUSTER_NAME', 'cafe-postcode'),
    'workers': env_int('Q_CLUSTER_WORKERS', 8),
    'recycle': env_int('Q_CLUSTER_RECYCLE', 500),
    'timeout': env_int('Q_CLUSTER_TIMEOUT', 300),
    'retry': env_int('Q_CLUSTER_RETRY', 300),
    'compress': True,
    'save_limit': env_int('Q_CLUSTER_SAVE_LIMIT', 5000),
    'queue_limit': env_int('Q_CLUSTER_QUEUE_LIMIT', 500),
    'cpu_affinity': env_int('Q_CLUSTER_CPU_AFFINITY', 1),
    'label': 'Django Q',
    'redis': redis_config_from_url(REDIS_URL or 'redis://127.0.0.1:6379/0'),
}
