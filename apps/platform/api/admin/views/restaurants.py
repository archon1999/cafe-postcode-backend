from rest_framework import generics
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.api.admin.serializers import (
    RestaurantActivationOptionsSerializer,
    RestaurantActivationResultSerializer,
    RestaurantActivationSerializer,
    RestaurantBalanceTopUpSerializer,
    RestaurantBalanceTransactionSerializer,
)
from apps.platform.helpers import get_restaurant_balance_transaction_model
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
    add_billing_period,
    create_restaurant_top_up,
    deactivate_restaurant_access,
    extend_restaurant_entitlement,
)
from apps.restaurants.api.admin.serializers import RestaurantSerializer
from apps.restaurants.helpers import generate_restaurant_auth_code, get_restaurant_model
from apps.restaurants.selectors.restaurants import get_restaurants_queryset_for_request
from apps.users.helpers import get_restaurant_profile_model, get_user_model
from common.api.paginations import SmallResultsSetPagination
from common.api.admin_permissions import AdminPermissionRequiredMixin

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
RestaurantBalanceTransaction = get_restaurant_balance_transaction_model()
RestaurantProfile = get_restaurant_profile_model()
Tariff = get_tariff_model()
User = get_user_model()


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
        billing_period = validated['billing_period']
        entitlement.tariff = tariff
        entitlement.is_custom = activation_type == 'custom'
        entitlement.is_active = True
        entitlement.starts_on = validated['starts_on']
        entitlement.billing_period = billing_period
        entitlement.expires_on = add_billing_period(validated['starts_on'], billing_period)
        entitlement.monthly_price = tariff.monthly_price if tariff is not None else validated.get('monthly_price')
        entitlement.yearly_price = tariff.yearly_price if tariff is not None else validated.get('yearly_price')
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
                is_staff=True,
            )
        else:
            admin_user.username = admin_username
            admin_user.role = admin_role
            admin_user.is_active = True
            admin_user.is_staff = True

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
        deactivate_restaurant_access(restaurant=restaurant, deactivated_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class RestaurantExtendView(AdminPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        entitlement = getattr(restaurant, 'entitlement', None)
        if entitlement is None or not entitlement.billing_period:
            raise serializers.ValidationError({'detail': 'Restaurant subscription period is not configured.'})

        extend_restaurant_entitlement(restaurant=restaurant, entitlement=entitlement)
        restaurant.refresh_from_db()
        return Response(RestaurantSerializer(restaurant).data, status=status.HTTP_200_OK)


class RestaurantResetPasswordView(AdminPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
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


class RestaurantRotateAuthCodeView(AdminPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        regenerate_restaurant_auth_code(restaurant)
        return Response(RestaurantSerializer(restaurant).data, status=status.HTTP_200_OK)


class RestaurantBalanceTransactionsView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = RestaurantBalanceTransactionSerializer
    pagination_class = SmallResultsSetPagination

    def _get_restaurant(self):
        if not hasattr(self, '_restaurant'):
            self._restaurant = get_restaurants_queryset_for_request(self.request).get(pk=self.kwargs['pk'])
        return self._restaurant

    def get_queryset(self):
        restaurant = self._get_restaurant()
        return (
            RestaurantBalanceTransaction.objects.filter(restaurant=restaurant)
            .select_related('performed_by')
            .order_by('-created_at', '-id')
        )


class RestaurantBalanceTopUpView(AdminPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = get_restaurants_queryset_for_request(request).get(pk=pk)
        serializer = RestaurantBalanceTopUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_item = create_restaurant_top_up(
            restaurant=restaurant,
            amount=serializer.validated_data['amount'],
            note=serializer.validated_data.get('note', ''),
            performed_by=request.user,
        )
        return Response(RestaurantBalanceTransactionSerializer(transaction_item).data, status=status.HTTP_200_OK)

__all__ = [
    'RestaurantActivateView',
    'RestaurantActivationOptionsView',
    'RestaurantBalanceTopUpView',
    'RestaurantBalanceTransactionsView',
    'RestaurantDeactivateView',
    'RestaurantExtendView',
    'RestaurantRotateAuthCodeView',
    'RestaurantResetPasswordView',
]
