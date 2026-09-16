from dataclasses import dataclass
from hashlib import sha256

from django.utils import timezone
from oauth2_provider.models import AccessToken

from apps.dashboard.services.restaurant_scope import (
    get_dashboard_accessible_restaurants,
)
from apps.platform.services import FeatureGateService
from apps.users.models import User
from .config import SCOPE, resource
from .models import AnalyticsConnection


class AnalyticsError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def accessible_restaurants(user):
    if (
        not user.is_active
        or user.is_superuser
        or user.get_restaurant_scope() is None
        or "dashboard.view" not in user.permission_codes
    ):
        raise AnalyticsError(
            "access_denied",
            "An active restaurant account with dashboard access is required.",
        )
    restaurants = tuple(get_dashboard_accessible_restaurants(user))
    for restaurant in restaurants:
        FeatureGateService().ensure_owner_dashboard_access(restaurant=restaurant)
    if not restaurants:
        raise AnalyticsError("access_denied", "No accessible branches.")
    return restaurants


@dataclass(frozen=True)
class Principal:
    user_id: str
    connection_id: str
    access_token_id: int


def authenticate_token(raw_token):
    token = (
        AccessToken.objects.select_related("accessbinding__connection", "user")
        .filter(
            token_checksum=sha256(raw_token.encode()).hexdigest(),
            expires__gt=timezone.now(),
        )
        .first()
    )
    if (
        token is None
        or token.resource != [resource()]
        or not token.allow_scopes([SCOPE])
    ):
        raise AnalyticsError("invalid_token", "Reconnect Cafe Postcode to continue.")
    try:
        connection = token.accessbinding.connection
    except (AttributeError, AnalyticsConnection.DoesNotExist):
        raise AnalyticsError(
            "invalid_token", "This token has no analytics consent."
        ) from None
    if (
        connection.user_id != token.user_id
        or connection.application_id != token.application_id
        or connection.resource != resource()
        or connection.revoked_at
        or connection.expires_at <= timezone.now()
    ):
        raise AnalyticsError(
            "invalid_token", "The analytics connection has expired or was revoked."
        )
    accessible_restaurants(token.user)
    return Principal(str(token.user_id), str(connection.pk), token.pk)


def resolve_scope(principal, branch_ids=None):
    """Recheck mutable policy on every query and stored-report read. Never return None."""
    connection = AnalyticsConnection.objects.filter(
        pk=principal.connection_id,
        user_id=principal.user_id,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
        resource=resource(),
    ).first()
    if (
        connection is None
        or not AccessToken.objects.filter(
            pk=principal.access_token_id,
            expires__gt=timezone.now(),
            accessbinding__connection=connection,
        ).exists()
    ):
        raise AnalyticsError(
            "invalid_token", "The analytics connection is no longer active."
        )
    user = User.objects.get(pk=principal.user_id)
    allowed = {
        str(r.pk): r
        for r in accessible_restaurants(user)
        if str(r.pk) in connection.restaurant_ids
    }
    requested = (
        list(allowed) if branch_ids is None else [str(value) for value in branch_ids]
    )
    if (
        not requested
        or len(requested) != len(set(requested))
        or any(key not in allowed for key in requested)
    ):
        raise AnalyticsError(
            "access_denied", "One or more selected branches are unavailable."
        )
    return tuple(allowed[key] for key in requested)
