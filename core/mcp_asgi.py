"""Run separately: poetry run uvicorn core.mcp_asgi:application --host 127.0.0.1 --port 8765."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.mcp")
os.environ.setdefault("DJANGO_SETTINGS_CLASS", "MCPSettings")

import class_settings

class_settings.setup()

import django

django.setup()

from apps.analytics_mcp.server import create_application

application = create_application()
