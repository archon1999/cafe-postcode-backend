from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from oauth2_provider.models import Grant, RefreshToken
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauthlib.oauth2 import InvalidGrantError, InvalidRequestError

from .config import resource
from .models import AccessBinding, AnalyticsConnection, AuthorizationBinding
from .policy import AnalyticsError, accessible_restaurants


class AnalyticsOAuthValidator(OAuth2Validator):
    @transaction.atomic
    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        if request.code_challenge_method != "S256" or getattr(
            request, "resource", None
        ) != [resource()]:
            raise InvalidRequestError(
                description="S256 PKCE and the exact MCP resource are required."
            )
        try:
            restaurants = accessible_restaurants(request.user)
        except AnalyticsError as error:
            raise InvalidRequestError(description=str(error)) from error
        super().save_authorization_code(client_id, code, request, *args, **kwargs)
        connection = AnalyticsConnection.objects.create(
            user=request.user,
            application=request.client,
            restaurant_ids=[str(r.pk) for r in restaurants],
            resource=resource(),
            expires_at=timezone.now() + timedelta(days=settings.MCP_CONNECTION_DAYS),
        )
        AuthorizationBinding.objects.create(
            grant=Grant.objects.get(code=code["code"], application=request.client),
            connection=connection,
        )

    def _save_bearer_token(self, token, request, *args, **kwargs):
        if request.grant_type == "authorization_code":
            binding = (
                AuthorizationBinding.objects.select_related("connection")
                .filter(
                    grant__code=request.code,
                    grant__application=request.client,
                )
                .first()
            )
            connection = binding.connection if binding else None
        elif request.grant_type == "refresh_token":
            previous = getattr(request, "refresh_token_instance", None)
            connection = (
                AnalyticsConnection.objects.filter(
                    token_family=previous.token_family
                ).first()
                if previous
                else None
            )
        else:
            connection = None
        if (
            connection is None
            or connection.revoked_at
            or connection.expires_at <= timezone.now()
            or connection.resource != resource()
            or connection.user_id != request.user.pk
        ):
            raise InvalidGrantError(
                description="Analytics consent is expired or revoked."
            )
        try:
            accessible_restaurants(request.user)
        except AnalyticsError as error:
            raise InvalidGrantError(description=str(error)) from error
        super()._save_bearer_token(token, request, *args, **kwargs)
        access = self._load_access_token(token["access_token"])
        if access.resource != [resource()]:
            raise InvalidGrantError(description="Invalid analytics audience.")
        AccessBinding.objects.create(access_token=access, connection=connection)
        refresh = RefreshToken.objects.filter(access_token=access).first()
        if refresh and connection.token_family is None:
            connection.token_family = refresh.token_family
            connection.save(update_fields=["token_family"])
