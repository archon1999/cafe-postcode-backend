from apps.organizations.models import Branch, Restaurant
from common.exceptions import NotFoundError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


ADMIN_RESTAURANT_HEADER = 'X-Admin-Restaurant-Id'
ADMIN_BRANCH_HEADER = 'X-Admin-Branch-Id'
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
        branch_id = _get_header_value(request, ADMIN_BRANCH_HEADER)

        if restaurant_id:
            restaurant = Restaurant.objects.filter(pk=restaurant_id).first()
            if restaurant is None:
                raise serializers.ValidationError({'restaurantId': _('Selected restaurant was not found.')})
            if branch_id:
                branch = Branch.objects.select_related('restaurant').filter(pk=branch_id).first()
                if branch is None:
                    raise serializers.ValidationError({'branchId': _('Selected branch was not found.')})
                if branch.restaurant_id != restaurant.id:
                    raise serializers.ValidationError(
                        {'branchId': _('Selected branch does not belong to the selected restaurant.')}
                    )
            return restaurant

        if branch_id:
            branch = Branch.objects.select_related('restaurant').filter(pk=branch_id).first()
            if branch is None:
                raise serializers.ValidationError({'branchId': _('Selected branch was not found.')})
            return branch.restaurant

    return None


def get_request_restaurant(request) -> Restaurant:
    restaurant = get_optional_request_restaurant(request)
    if restaurant is not None:
        return restaurant

    if _is_admin_superuser_request(request):
        raise serializers.ValidationError(
            {'restaurantId': _('Restaurant selection is required for superuser admin requests.')}
        )

    if getattr(request.user, 'restaurant_id', None):
        return request.user.restaurant

    restaurant = Restaurant.objects.order_by('created_at').first()
    if restaurant is None:
        raise NotFoundError('Restaurant is not configured yet.')
    return restaurant


def get_optional_request_branch(request, restaurant: Restaurant | None = None) -> Branch | None:
    if _is_admin_superuser_request(request):
        branch_id = _get_header_value(request, ADMIN_BRANCH_HEADER)
        if not branch_id:
            return None

        branch = Branch.objects.select_related('restaurant').filter(pk=branch_id).first()
        if branch is None:
            raise serializers.ValidationError({'branchId': _('Selected branch was not found.')})
        if restaurant is not None and branch.restaurant_id != restaurant.id:
            raise serializers.ValidationError(
                {'branchId': _('Selected branch does not belong to the selected restaurant.')}
            )
        return branch

    return None


def get_request_branch(request, restaurant: Restaurant | None = None) -> Branch:
    branch = get_optional_request_branch(request, restaurant)
    if branch is not None:
        return branch

    if getattr(request.user, 'branch_id', None):
        return request.user.branch

    restaurant = restaurant or get_request_restaurant(request)
    branch = restaurant.branches.filter(is_default=True).order_by('created_at').first()
    if branch is None:
        branch = restaurant.branches.order_by('created_at').first()
    if branch is None:
        raise NotFoundError('Branch is not configured yet.')
    return branch
