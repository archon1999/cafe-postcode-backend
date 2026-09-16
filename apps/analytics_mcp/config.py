from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

SCOPE = "analytics:read"


def origin():
    value = settings.MCP_PUBLIC_ORIGIN.rstrip("/")
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    if (
        not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http" and local and not settings.DJANGO_PRODUCTION
            )
        )
    ):
        raise ImproperlyConfigured(
            "MCP_PUBLIC_ORIGIN must be an HTTPS origin (HTTP loopback is development-only)."
        )
    return value


def resource():
    return origin() + "/mcp"
