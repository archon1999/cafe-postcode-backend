"""Settings for the dedicated MCP process; no POS/admin routes are exposed."""

from . import CoreSettings


class MCPSettings(CoreSettings):
    ROOT_URLCONF = "apps.analytics_mcp.urls"
    DISABLE_CSRF_CHECKS = False
    SESSION_COOKIE_NAME = "cafe_mcp_session"
    CSRF_COOKIE_NAME = "cafe_mcp_csrf"
    LOGIN_URL = "/oauth/login/"
    LOGIN_REDIRECT_URL = "/oauth/connections/"
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]
