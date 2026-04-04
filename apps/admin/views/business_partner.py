from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import (
    RestaurantActivationOptionsSerializer,
    RestaurantActivationResultSerializer,
    RestaurantActivationSerializer,
    RestaurantSerializer,
)
from apps.admin.support.business_partner import activation_permission_queryset, activation_role_queryset
from apps.organizations.models import FeatureConfig, Restaurant, RestaurantEntitlement, Tariff
from apps.organizations.models.restaurant import generate_restaurant_auth_code

from apps.admin.support.business_partner import (
    generate_password,
    generate_unique_username,
    get_restaurant_admin_role_for_source,
    normalize_username_base,
)


def get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.prefetch_related('feature_config').select_related('business_partner').order_by('name')
    if request.user.is_superuser or request.user.actor_type == request.user.ActorType.PRODUCT_OWNER:
        return queryset

    business_partner = request.user.get_business_partner_scope()
    if business_partner is not None:
        return queryset.filter(business_partner=business_partner)

    restaurant = request.user.get_restaurant_scope()
    if restaurant is not None:
        return queryset.filter(pk=restaurant.id)

    return queryset.none()


def regenerate_restaurant_auth_code(restaurant: Restaurant) -> Restaurant:
    code = generate_restaurant_auth_code()
    while Restaurant.objects.filter(auth_code=code).exclude(pk=restaurant.pk).exists():
        code = generate_restaurant_auth_code()

    restaurant.auth_code = code
    restaurant.save(update_fields=['auth_code', 'updated_at'])
    return restaurant


class RestaurantActivateView(AdminPermissionRequiredMixin, APIView):

    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        serializer = RestaurantActivationSerializer(data=request.data)
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
        entitlement.starts_on = validated['starts_on']
        entitlement.monthly_price = tariff.monthly_price if tariff is not None else None
        entitlement.yearly_price = tariff.yearly_price if tariff is not None else None
        entitlement.save()
        entitlement.permissions.clear()
        entitlement.allowed_roles.clear()
        if activation_type == 'custom':
            entitlement.allowed_roles.set(allowed_roles)
            entitlement.permissions.set(permissions)

        password = generate_password()
        admin_user = restaurant.users.filter(actor_type=User.ActorType.RESTAURANT_ADMIN).order_by('created_at').first()
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
                ui_mode=User.UiMode.ADMIN,
                actor_type=User.ActorType.RESTAURANT_ADMIN,
                restaurant=restaurant,
                role=admin_role,
                is_active=True,
            )
        else:
            admin_user.username = admin_username
            admin_user.role = admin_role
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
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        feature_config.enabled_roles = sorted(entitlement.get_effective_role_codes())
        feature_config.save(update_fields=['enabled_roles', 'updated_at'])

        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantActivationOptionsView(AdminPermissionRequiredMixin, APIView):

    def get(self, request):
        payload = {
            'tariffs': Tariff.objects.filter(is_active=True).prefetch_related('permissions', 'allowed_roles').order_by('name'),
            'roles': activation_role_queryset(),
            'permissions': activation_permission_queryset(),
        }
        return Response(RestaurantActivationOptionsSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantDeactivateView(AdminPermissionRequiredMixin, APIView):

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


class RestaurantRotateAuthCodeView(AdminPermissionRequiredMixin, APIView):

    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        regenerate_restaurant_auth_code(restaurant)
        return Response(RestaurantSerializer(restaurant).data, status=status.HTTP_200_OK)
