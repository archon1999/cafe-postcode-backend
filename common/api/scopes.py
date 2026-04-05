from apps.restaurants.models import Restaurant
from common.exceptions import NotFoundError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


ADMIN_RESTAURANT_HEADER = 'X-Admin-Restaurant-Id'
ADMIN_API_PATH_PREFIX = '/api/v1/admin/'


def _is_admin_superuser_request(request) -> bool:
    return bool(
        getattr(request.user, 'is_authenticated', False)
        and getattr(request.user, 'is_superuser', False)
        and request.path.startswith(ADMIN_API_PATH_PREFIX)
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

    user_restaurant = getattr(request.user, 'get_restaurant_scope', lambda: None)()
    if user_restaurant is not None:
        return user_restaurant

    restaurant = Restaurant.objects.order_by('created_at').first()
    if restaurant is None:
        raise NotFoundError('Restaurant is not configured yet.')
    return restaurant
