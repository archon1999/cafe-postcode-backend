Q_CLUSTER = {
    'name': 'KEP',
    'workers': 8,
    'recycle': 500,
    'timeout': 300,
    'retry': 300,
    'compress': True,
    'save_limit': 5000,
    'queue_limit': 500,
    'cpu_affinity': 1,
    'label': 'Django Q',
    'redis': {
        'host': '127.0.0.1',
        'port': 6379,
        'db': 0,
    }
}
