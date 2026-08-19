from apps.restaurants.models import Restaurant
from common.exceptions import NotFoundError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied


ADMIN_RESTAURANT_HEADER = 'X-Admin-Restaurant-Id'
ADMIN_SCOPED_PATH_PREFIXES = (
    '/api/v1/admin/',
    '/api/v1/local-agent/',
)
ADMIN_SCOPED_EXACT_PATHS = frozenset(
    {
        # The POS status route is also rendered inside the superadmin restaurant
        # context.  It is outside the admin URL prefix, but must honor the same
        # explicit branch selector for an authenticated superuser.
        '/api/v1/system/status/',
    }
)


def _is_admin_superuser_request(request) -> bool:
    return bool(
        getattr(request.user, 'is_authenticated', False)
        and getattr(request.user, 'is_superuser', False)
        and (
            request.path.startswith(ADMIN_SCOPED_PATH_PREFIXES)
            or request.path in ADMIN_SCOPED_EXACT_PATHS
        )
    )


def _get_header_value(request, header_name: str) -> str | None:
    header_value = request.headers.get(header_name)
    if header_value is None:
        return None

    normalized_value = str(header_value).strip()
    return normalized_value or None


def get_optional_request_restaurant(request) -> Restaurant | None:
    if _is_admin_superuser_request(request):
        restaurant_id = _get_header_value(request, ADMIN_RESTAURANT_HEADER)
        if restaurant_id:
            restaurant = Restaurant.objects.filter(pk=restaurant_id).first()
            if restaurant is None:
                raise serializers.ValidationError({'restaurantId': _('Selected restaurant was not found.')})
            return restaurant
        return None

    return getattr(request.user, 'get_restaurant_scope', lambda: None)()


def get_request_restaurant(request) -> Restaurant:
    restaurant = get_optional_request_restaurant(request)
    if restaurant is not None:
        return restaurant

    if _is_admin_superuser_request(request):
        raise serializers.ValidationError(
            {'restaurantId': _('Restaurant selection is required for superuser admin requests.')}
        )

    # A tenant-aware API must never guess a restaurant.  The historical
    # fallback to the first row meant that an authenticated account without a
    # profile could operate on an unrelated tenant if an endpoint permission
    # was ever assigned by mistake.  Explicit superuser selection is handled
    # above; every other caller must carry a real restaurant scope.
    if getattr(request.user, 'is_authenticated', False):
        raise PermissionDenied(_('Restaurant access is not available for this account.'))

    raise NotFoundError('Restaurant is not configured for this request.')
