"""
Django middleware configuration.
"""

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',

    # Debug toolbar middleware
    # "debug_toolbar.middleware.DebugToolbarMiddleware",

    # Compression and security middleware
    'django.middleware.security.SecurityMiddleware',
    'core.admin_access.DjangoAdminNetworkMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    
    # Session and locale middleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'core.middleware.ActivateTimezoneMiddleware',
    "django.middleware.locale.LocaleMiddleware",
    'core.middleware.RequestLanguageMiddleware',
    
    # Common middleware
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    
    # Authentication middleware
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.observability.RequestLogMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # Custom middleware
    'core.middleware.ParamsSnakeCaseMiddleware',
    'core.middleware.DisableCSRFMiddleware',
    'core.middleware.SystemTimeAdderMiddleware',
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]
