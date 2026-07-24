DEFAULT_APPS = [
    'django.contrib.humanize',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

LOCAL_APPS = [
    'apps.dashboard',
    'apps.users',
    'apps.platform',
    'apps.restaurants',
    'apps.floor',
    'apps.catalog',
    'apps.sales',
    'apps.billing',
    'apps.kitchen',
    'apps.reporting',
    'apps.telegram_reports',
    'apps.integrations',
    'apps.landing',
    'apps.local_agents',
    'apps.printing',
]

THIRD_PARTY_APPS = [
    'django_prometheus',
    'modeltranslation',
    'corsheaders',
    'storages',
    'django_filters',
    'django_q',
    'rest_framework',
    'channels',
    'rest_framework.authtoken',
    'drf_yasg',
]

INSTALLED_APPS = THIRD_PARTY_APPS + DEFAULT_APPS + LOCAL_APPS
