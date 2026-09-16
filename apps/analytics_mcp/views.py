from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from oauth2_provider.views import AuthorizationView, TokenView

from common.api.client_ip import get_client_ip
from .config import SCOPE, origin, resource
from .models import AnalyticsConnection
from .policy import AnalyticsError, accessible_restaurants
from .rate_limit import rate_allowed


class AnalyticsLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        try:
            accessible_restaurants(user)
        except AnalyticsError as error:
            raise ValidationError(str(error), code="access_denied") from error


class AnalyticsLoginView(LoginView):
    template_name = "analytics_mcp/login.html"
    authentication_form = AnalyticsLoginForm
    next_page = "/oauth/connections/"

    def post(self, request, *args, **kwargs):
        ip_ok = rate_allowed(
            "login-ip:" + (get_client_ip(request) or "unknown"), 20, 300
        )
        account_ok = rate_allowed(
            "login-account:" + request.POST.get("username", "").casefold(), 10, 300
        )
        if not ip_ok or not account_ok:
            return HttpResponse("Too many login attempts. Try again later.", status=429)
        return super().post(request, *args, **kwargs)


class AnalyticsAuthorizationView(AuthorizationView):
    template_name = "analytics_mcp/authorize.html"
    login_url = "/oauth/login/"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            try:
                accessible_restaurants(request.user)
            except AnalyticsError as error:
                return HttpResponse(str(error), status=403)
        values = request.POST if request.method == "POST" else request.GET
        if (
            values.get("resource") != resource()
            or values.get("code_challenge_method") != "S256"
        ):
            return JsonResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Exact MCP resource and PKCE S256 required.",
                },
                status=400,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["branches"] = accessible_restaurants(self.request.user)
        return context


class LimitedTokenView(TokenView):
    def post(self, request, *args, **kwargs):
        if not rate_allowed("token:" + (get_client_ip(request) or "unknown"), 120):
            return JsonResponse({"error": "temporarily_unavailable"}, status=429)
        return super().post(request, *args, **kwargs)


@require_GET
def authorization_metadata(request):
    base = origin()
    return JsonResponse(
        {
            "issuer": base,
            "authorization_endpoint": base + "/oauth/authorize/",
            "token_endpoint": base + "/oauth/token/",
            "revocation_endpoint": base + "/oauth/revoke/",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
                "none",
            ],
            "scopes_supported": [SCOPE],
        }
    )


@require_GET
def resource_metadata(request):
    return JsonResponse(
        {
            "resource": resource(),
            "authorization_servers": [origin()],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "Cafe Postcode Analytics",
        }
    )


@login_required(login_url="/oauth/login/")
@require_http_methods(["GET", "POST"])
def connections(request):
    if request.method == "POST":
        try:
            connection_id = UUID(request.POST.get("connection_id", ""))
        except (ValueError, TypeError):
            return HttpResponse("Invalid connection ID.", status=400)
        AnalyticsConnection.objects.filter(
            user=request.user,
            pk=connection_id,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())
        return redirect("/oauth/connections/")
    return render(
        request,
        "analytics_mcp/connections.html",
        {
            "connections": AnalyticsConnection.objects.filter(
                user=request.user,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("application")
            .order_by("-created_at"),
        },
    )
