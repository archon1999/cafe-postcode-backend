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
    'apps.admin',
    'apps.accounts',
    'apps.organizations',
    'apps.floor',
    'apps.catalog',
    'apps.orders',
    'apps.kitchen',
    'apps.reports',
    'apps.integrations',
]

THIRD_PARTY_APPS = [
    'modeltranslation',
    'corsheaders',
    'django_filters',
    'rest_framework',
    'channels',
    'rest_framework.authtoken',
    'drf_yasg',
]

INSTALLED_APPS = THIRD_PARTY_APPS + DEFAULT_APPS + LOCAL_APPS
