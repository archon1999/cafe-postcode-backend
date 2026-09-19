"""Shared authorization for the admin assistant and the management bot.

Always resolve current permissions and ownership, including after Telegram link.
Business partners may manage only restaurants assigned to their active profile.
"""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers
from apps.restaurants.models import Restaurant


def restaurants_for(user):
    queryset = Restaurant.objects.filter(is_active=True)
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    if user.is_superuser:
        return queryset
    partner = user.get_business_partner_scope()
    if partner is not None and partner.status == 'active':
        return queryset.filter(business_partner=partner)
    restaurant = user.get_restaurant_scope()
    if user.role_code in ('restaurant_admin', 'fast_food_admin') and user.restaurant_access_active and restaurant:
        return queryset.filter(pk=restaurant.pk)
    return queryset.none()


def require_access(user, restaurant_id, resource='catalog_items', action='create'):
    restaurant_id = serializers.UUIDField().run_validation(restaurant_id)
    restaurant = get_object_or_404(restaurants_for(user), pk=restaurant_id)
    if user.is_superuser or user.get_business_partner_scope() is not None:
        return restaurant
    if f'{resource}.{action}' not in user.permission_codes:
        raise PermissionDenied('Bu amal uchun ruxsat mavjud emas.')
    return restaurant
