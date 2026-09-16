from django.contrib.auth.views import LogoutView
from django.http import JsonResponse
from django.urls import path
from oauth2_provider.views import RevokeTokenView
from core.health import readyz
from . import views

urlpatterns = [
    path("assets/<str:name>", views.brand_asset),
    path("readyz/", readyz),
    path(
        "healthz/",
        lambda request: JsonResponse({"status": "ok", "service": "analytics-mcp"}),
    ),
    path(".well-known/oauth-authorization-server", views.authorization_metadata),
    path(".well-known/oauth-protected-resource", views.resource_metadata),
    path(".well-known/oauth-protected-resource/mcp", views.resource_metadata),
    path("oauth/login/", views.AnalyticsLoginView.as_view(), name="mcp-login"),
    path("oauth/logout/", LogoutView.as_view(next_page="/oauth/login/")),
    path(
        "oauth/authorize/",
        views.AnalyticsAuthorizationView.as_view(),
        name="mcp-authorize",
    ),
    path("oauth/token/", views.LimitedTokenView.as_view(), name="mcp-token"),
    path("oauth/revoke/", RevokeTokenView.as_view(), name="mcp-revoke"),
    path("oauth/connections/", views.connections, name="mcp-connections"),
]
