from django.utils import timezone
from rest_framework import generics
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.api.admin.serializers import (
    CUSTOM_TARIFF_PERMISSION_CODE,
    RestaurantActivationOptionsSerializer,
    RestaurantActivationResultSerializer,
    RestaurantActivationSerializer,
    RestaurantTariffChangePreviewQuerySerializer,
    RestaurantTariffChangeSerializer,
)
from apps.platform.api.admin.permissions import NonRestaurantPermissionRequiredMixin
from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.platform.selectors.business_partners import (
    activation_permission_queryset,
    activation_role_queryset,
    generate_password,
    generate_unique_username,
    get_restaurant_admin_role_for_source,
    normalize_username_base,
)
from apps.platform.services import (
    deactivate_restaurant_access,
    change_restaurant_tariff,
    get_restaurant_tariff_change_preview,
)
from apps.restaurants.api.admin.serializers import RestaurantSerializer
from apps.restaurants.helpers import get_restaurant_model
from apps.restaurants.selectors.restaurants import get_restaurants_queryset_for_request
from apps.users.helpers import get_restaurant_profile_model, get_user_model

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
RestaurantProfile = get_restaurant_profile_model()
Tariff = get_tariff_model()
User = get_user_model()


class RestaurantActivateView(NonRestaurantPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = generics.get_object_or_404(
            get_restaurants_queryset_for_request(request), pk=pk
        )
        serializer = RestaurantActivationSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        entitlement, _ = RestaurantEntitlement.objects.get_or_create(restaurant=restaurant)
        tariff = validated.get('tariff')
        activation_type = validated.get('activation_type', 'tariff')
        allowed_roles = list(validated.get('allowed_roles', []))
        permissions = list(validated.get('permissions', []))
        entitlement.tariff = tariff
        entitlement.is_custom = activation_type == 'custom'
        entitlement.is_active = True
        entitlement.save()
        entitlement.permissions.clear()
        entitlement.allowed_roles.clear()
        if activation_type == 'custom':
            entitlement.allowed_roles.set(allowed_roles)
            entitlement.permissions.set(permissions)

        password = generate_password()
        admin_user = User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            role__code__in=('restaurant_admin', 'fast_food_admin'),
        ).order_by('created_at').first()
        admin_username = generate_unique_username(
            f"admin-{normalize_username_base(restaurant.name, 'restaurant')}",
            exclude_user=admin_user,
        )
        admin_role = get_restaurant_admin_role_for_source(tariff if tariff is not None else allowed_roles)
        if admin_user is None:
            admin_user = User.objects.create(
                username=admin_username,
                full_name=f'{restaurant.name} Admin',
                phone=restaurant.phone,
                role=admin_role,
                is_active=True,
                is_staff=False,
            )
        else:
            admin_user.username = admin_username
            admin_user.role = admin_role
            admin_user.is_active = True
            if not admin_user.is_superuser:
                admin_user.is_staff = False

        admin_user.set_password(password)
        admin_user.save()
        RestaurantProfile.objects.update_or_create(
            user=admin_user,
            defaults={'restaurant': restaurant},
        )

        restaurant.is_active = True
        restaurant.activated_at = timezone.now()
        restaurant.deactivated_at = None
        restaurant.save(update_fields=['is_active', 'activated_at', 'deactivated_at', 'updated_at'])

        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantActivationOptionsView(NonRestaurantPermissionRequiredMixin, APIView):
    def get(self, request):
        payload = {
            'tariffs': Tariff.objects.filter(is_active=True).prefetch_related('permissions', 'allowed_roles').order_by('name'),
            'roles': activation_role_queryset(),
            'permissions': activation_permission_queryset(),
            'custom_tariff_allowed': CUSTOM_TARIFF_PERMISSION_CODE in set(request.user.permission_codes),
        }
        return Response(RestaurantActivationOptionsSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantTariffChangeView(NonRestaurantPermissionRequiredMixin, APIView):
    def _get_restaurant(self, request, pk):
        return generics.get_object_or_404(
            get_restaurants_queryset_for_request(request), pk=pk
        )

    def get(self, request, pk):
        restaurant = self._get_restaurant(request, pk)
        serializer = RestaurantTariffChangePreviewQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        preview = get_restaurant_tariff_change_preview(
            restaurant=restaurant,
            target_tariff=serializer.validated_data['tariff'],
        )
        return Response(preview, status=status.HTTP_200_OK)

    def post(self, request, pk):
        restaurant = self._get_restaurant(request, pk)
        serializer = RestaurantTariffChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_users = change_restaurant_tariff(
            restaurant=restaurant,
            target_tariff=serializer.validated_data['tariff'],
            role_mappings=serializer.validated_data['role_mappings'],
        )
        restaurant.refresh_from_db()
        return Response(
            {
                'restaurant': RestaurantSerializer(restaurant).data,
                'updated_users': updated_users,
            },
            status=status.HTTP_200_OK,
        )


class RestaurantDeactivateView(NonRestaurantPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = generics.get_object_or_404(
            get_restaurants_queryset_for_request(request), pk=pk
        )
        deactivate_restaurant_access(restaurant=restaurant, deactivated_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class RestaurantResetPasswordView(NonRestaurantPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = generics.get_object_or_404(
            get_restaurants_queryset_for_request(request), pk=pk
        )
        admin_user = User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            role__code__in=('restaurant_admin', 'fast_food_admin'),
        ).order_by('created_at').first()
        if admin_user is None:
            raise serializers.ValidationError({'detail': 'Restaurant admin user was not found.'})
        password = generate_password()
        admin_user.set_password(password)
        admin_user.save(update_fields=['password'])
        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


__all__ = [
    'RestaurantActivateView',
    'RestaurantActivationOptionsView',
    'RestaurantDeactivateView',
    'RestaurantResetPasswordView',
    'RestaurantTariffChangeView',
]
