"""Settings for the dedicated MCP process; no POS/admin routes are exposed."""

from . import CoreSettings


class MCPSettings(CoreSettings):
    DATABASES = {
        alias: {**config, "CONN_MAX_AGE": 0}
        for alias, config in CoreSettings.DATABASES.items()
    }
    ROOT_URLCONF = "apps.analytics_mcp.urls"
    AUTHENTICATION_BACKENDS = ["apps.analytics_mcp.backends.AnalyticsModelBackend"]
    DISABLE_CSRF_CHECKS = False
    SESSION_COOKIE_NAME = "cafe_mcp_session"
    CSRF_COOKIE_NAME = "cafe_mcp_csrf"
    LOGIN_URL = "/oauth/login/"
    LOGIN_REDIRECT_URL = "/oauth/connections/"
    DATA_UPLOAD_MAX_MEMORY_SIZE = 65536
    DATA_UPLOAD_MAX_NUMBER_FIELDS = 30
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "apps.analytics_mcp.middleware.OAuthSecurityHeaders",
    ]
