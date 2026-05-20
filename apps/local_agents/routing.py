from django.urls import path

from apps.local_agents.consumers import LocalAgentConsumer

websocket_urlpatterns = [
    path('ws/local-agent/', LocalAgentConsumer.as_asgi()),
]
