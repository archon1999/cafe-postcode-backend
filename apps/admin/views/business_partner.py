from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Permission, Role, User
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import RestaurantActivationResultSerializer, RestaurantActivationSerializer
from apps.organizations.models import RestaurantEntitlement

from ._business_helpers import (
    generate_password,
    generate_unique_username,
    get_restaurant_admin_role,
    get_restaurants_queryset_for_request,
    normalize_username_base,
)


class RestaurantActivateView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'restaurants.activate'

    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        serializer = RestaurantActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        entitlement, _ = RestaurantEntitlement.objects.get_or_create(restaurant=restaurant)
        entitlement.tariff = validated.get('tariff')
        entitlement.is_custom = validated.get('custom_tariff', False)
        entitlement.is_active = True
        entitlement.starts_on = validated['starts_on']
        entitlement.monthly_price = validated.get('monthly_price') or getattr(validated.get('tariff'), 'monthly_price', None)
        entitlement.yearly_price = validated.get('yearly_price') or getattr(validated.get('tariff'), 'yearly_price', None)
        entitlement.operational_settings = validated.get('operational_settings', {})
        entitlement.save()

        custom_enabled_role_codes = [
            code
            for code in entitlement.operational_settings.get('enabled_roles', [])
            if isinstance(code, str) and code
        ]
        derived_roles = list(
            Role.objects.filter(is_system=True, code__in=custom_enabled_role_codes).prefetch_related('permissions')
        )
        derived_permission_ids = sorted(
            {
                permission.id
                for role in derived_roles
                for permission in role.permissions.all()
            }
        )
        entitlement_permissions = validated.get('permissions')
        entitlement_allowed_roles = validated.get('allowed_roles')
        if validated.get('custom_tariff', False):
            if entitlement_permissions is None:
                entitlement_permissions = list(Permission.objects.filter(id__in=derived_permission_ids))
            if entitlement_allowed_roles is None:
                entitlement_allowed_roles = derived_roles

        entitlement.permissions.set(entitlement_permissions or [])
        entitlement.allowed_roles.set(entitlement_allowed_roles or [])

        password = generate_password()
        admin_user = restaurant.users.filter(actor_type=User.ActorType.RESTAURANT_ADMIN).order_by('created_at').first()
        admin_username = generate_unique_username(
            f"admin-{normalize_username_base(restaurant.name, 'restaurant')}",
            exclude_user=admin_user,
        )
        if admin_user is None:
            admin_user = User.objects.create(
                username=admin_username,
                full_name=f'{restaurant.name} Admin',
                phone=restaurant.phone,
                ui_mode=User.UiMode.ADMIN,
                actor_type=User.ActorType.RESTAURANT_ADMIN,
                restaurant=restaurant,
                role=get_restaurant_admin_role(),
                is_active=True,
            )
        else:
            admin_user.username = admin_username
            admin_user.role = get_restaurant_admin_role()
            admin_user.actor_type = User.ActorType.RESTAURANT_ADMIN
            admin_user.restaurant = restaurant
            admin_user.ui_mode = User.UiMode.ADMIN
            admin_user.is_active = True

        admin_user.set_password(password)
        admin_user.save()

        restaurant.is_active = True
        restaurant.activated_at = timezone.now()
        restaurant.deactivated_at = None
        restaurant.save(update_fields=['is_active', 'activated_at', 'deactivated_at', 'updated_at'])

        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantDeactivateView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'restaurants.deactivate'

    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        restaurant.is_active = False
        restaurant.deactivated_at = timezone.now()
        restaurant.save(update_fields=['is_active', 'deactivated_at', 'updated_at'])
        entitlement = getattr(restaurant, 'entitlement', None)
        if entitlement is not None:
            entitlement.is_active = False
            entitlement.save(update_fields=['is_active', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class RestaurantResetPasswordView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'restaurants.reset_password'

    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        admin_user = restaurant.users.filter(actor_type=User.ActorType.RESTAURANT_ADMIN).order_by('created_at').first()
        if admin_user is None:
            raise serializers.ValidationError({'detail': 'Restaurant admin user was not found.'})
        password = generate_password()
        admin_user.set_password(password)
        admin_user.save(update_fields=['password'])
        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)
