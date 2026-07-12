import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

import class_settings
from class_settings import env

env.read_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ.setdefault('DJANGO_SETTINGS_CLASS', 'CoreSettings')
class_settings.setup()

django_asgi_application = get_asgi_application()

from apps.local_agents.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        'http': django_asgi_application,
        'websocket': AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
