from uuid import UUID
from pathlib import Path
import os
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from oauth2_provider.views import AuthorizationView, TokenView

from common.api.client_ip import get_client_ip
from apps.users.models import AdminMFAProfile
from apps.users.services.admin_mfa import (
    decrypt_mfa_secret,
    totp_code_digest,
    verify_totp,
)
from .config import SCOPE, origin, resource
from .models import AnalyticsConnection
from .policy import AnalyticsError, accessible_restaurants
from .rate_limit import rate_allowed


@require_GET
def domain_challenge(request):
    """Serve only the verification value issued by OpenAI; never a placeholder."""
    token = os.environ.get("MCP_OPENAI_DOMAIN_CHALLENGE", "")
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise Http404
    response = HttpResponse(token, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def brand_asset(request, name):
    types = {"admin-logo.webp": "image/webp", "nunito-sans.woff2": "font/woff2"}
    if name not in types:
        raise Http404
    response = FileResponse(
        Path(__file__).with_name("assets").joinpath(name).open("rb"),
        content_type=types[name],
    )
    response["Cache-Control"] = "public, max-age=604800"
    return response


class AnalyticsLoginForm(AuthenticationForm):
    otp = forms.CharField(
        required=False,
        max_length=6,
        widget=forms.PasswordInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
            }
        ),
    )

    @transaction.atomic
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        try:
            accessible_restaurants(user)
        except AnalyticsError as error:
            raise ValidationError(str(error), code="access_denied") from error
        profile = AdminMFAProfile.objects.select_for_update().filter(user=user).first()
        if profile is None:
            if settings.ADMIN_MFA_REQUIRED:
                raise ValidationError(
                    "Avval Admin panelda ikki bosqichli tasdiqlashni sozlang."
                )
            return
        self.mfa_needed = True
        code = self.cleaned_data.get("otp", "")
        secret = decrypt_mfa_secret(profile.encrypted_secret)
        counter = verify_totp(
            secret,
            code,
            last_counter=profile.last_totp_counter,
            last_code_digest=profile.last_totp_code_digest,
        )
        if counter is None:
            raise ValidationError(
                "Authenticator ilovasidagi yangi 6 xonali kodni kiriting."
            )
        profile.last_totp_counter = counter
        profile.last_totp_code_digest = totp_code_digest(secret, code)
        profile.save(update_fields=["last_totp_counter", "last_totp_code_digest"])


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
