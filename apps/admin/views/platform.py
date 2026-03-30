import secrets
import string

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers.platform import (
    BusinessPartnerSerializer,
    PartnerActivationResultSerializer,
    RestaurantActivationResultSerializer,
    RestaurantActivationSerializer,
    TariffSerializer,
)
from apps.organizations.models import BusinessPartner, Restaurant, RestaurantEntitlement, Tariff
from common.api.query_params import apply_ordering, get_bool_query_param, get_ordering_query_param, get_str_query_param


BUSINESS_PARTNER_ORDERING_FIELDS = {
    'companyName': 'company_name',
    'inn': 'inn',
    'status': 'status',
    'activatedAt': 'activated_at',
}
TARIFF_ORDERING_FIELDS = {
    'name': 'name',
    'classification': 'classification',
    'monthlyPrice': 'monthly_price',
    'yearlyPrice': 'yearly_price',
    'isActive': 'is_active',
}


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _filter_partners(queryset, request):
    search = get_str_query_param(request.query_params, 'search')
    is_active = get_bool_query_param(request.query_params, 'is_active')
    ordering = get_ordering_query_param(request.query_params, BUSINESS_PARTNER_ORDERING_FIELDS)

    if search:
        queryset = queryset.filter(
            Q(company_name__icontains=search)
            | Q(legal_name__icontains=search)
            | Q(inn__icontains=search)
            | Q(phone__icontains=search)
        )
    if is_active is not None:
        queryset = queryset.filter(status=BusinessPartner.Status.ACTIVE if is_active else BusinessPartner.Status.INACTIVE)
    return apply_ordering(queryset, ordering, default_ordering=('company_name',))


def _filter_tariffs(queryset, request):
    search = get_str_query_param(request.query_params, 'search')
    is_active = get_bool_query_param(request.query_params, 'is_active')
    ordering = get_ordering_query_param(request.query_params, TARIFF_ORDERING_FIELDS)

    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(classification__icontains=search)
            | Q(description__icontains=search)
        )
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    return apply_ordering(queryset, ordering, default_ordering=('name',))


def _get_business_partner_role() -> Role:
    return Role.objects.get(code='business_partner')


def _get_restaurant_admin_role() -> Role:
    return Role.objects.get(code='restaurant_admin')


def _get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.select_related('business_partner').prefetch_related('entitlement', 'feature_config').order_by('name')
    if request.user.is_superuser or request.user.actor_type == User.ActorType.PRODUCT_OWNER:
        return queryset
    if request.user.actor_type == User.ActorType.BUSINESS_PARTNER and request.user.business_partner_id:
        return queryset.filter(business_partner_id=request.user.business_partner_id)
    if request.user.restaurant_id:
        return queryset.filter(pk=request.user.restaurant_id)
    return queryset.none()


class BusinessPartnerListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_permission_code(self):
        return 'partners.view' if self.request.method == 'GET' else 'partners.manage'

    def get_queryset(self):
        return _filter_partners(BusinessPartner.objects.select_related('owner_user'), self.request)


class BusinessPartnerDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_permission_code(self):
        return 'partners.view' if self.request.method == 'GET' else 'partners.manage'

    def get_queryset(self):
        return BusinessPartner.objects.select_related('owner_user').order_by('company_name')


class BusinessPartnerActivateView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'partners.activate'

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        username = partner.owner_user.username if partner.owner_user_id else f'partner_{partner.inn}'
        password = _generate_password()
        user = partner.owner_user

        if user is None:
            user = User.objects.create(
                username=username,
                full_name=partner.company_name,
                phone=partner.phone,
                ui_mode=User.UiMode.ADMIN,
                actor_type=User.ActorType.BUSINESS_PARTNER,
                business_partner=partner,
                role=_get_business_partner_role(),
                is_active=True,
            )
            partner.owner_user = user
        else:
            user.business_partner = partner
            user.role = _get_business_partner_role()
            user.actor_type = User.ActorType.BUSINESS_PARTNER
            user.ui_mode = User.UiMode.ADMIN
            user.is_active = True

        user.set_password(password)
        user.save()

        partner.status = BusinessPartner.Status.ACTIVE
        partner.activated_at = timezone.now()
        partner.deactivated_at = None
        partner.save(update_fields=['owner_user', 'status', 'activated_at', 'deactivated_at', 'updated_at'])

        payload = {'partner': partner, 'username': user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class BusinessPartnerDeactivateView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'partners.deactivate'

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        partner.status = BusinessPartner.Status.INACTIVE
        partner.deactivated_at = timezone.now()
        partner.save(update_fields=['status', 'deactivated_at', 'updated_at'])
        if partner.owner_user_id:
            partner.owner_user.is_active = False
            partner.owner_user.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessPartnerResetPasswordView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'partners.reset_password'

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        if partner.owner_user is None:
            raise serializers.ValidationError({'detail': 'Business partner is not activated yet.'})
        password = _generate_password()
        partner.owner_user.set_password(password)
        partner.owner_user.save(update_fields=['password'])
        payload = {'partner': partner, 'username': partner.owner_user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class TariffListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = TariffSerializer

    def get_permission_code(self):
        return 'tariffs.view' if self.request.method == 'GET' else 'tariffs.manage'

    def get_queryset(self):
        return _filter_tariffs(Tariff.objects.prefetch_related('permissions', 'allowed_roles'), self.request)


class TariffDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = TariffSerializer

    def get_permission_code(self):
        return 'tariffs.view' if self.request.method == 'GET' else 'tariffs.manage'

    def get_queryset(self):
        return Tariff.objects.prefetch_related('permissions', 'allowed_roles').order_by('name')


class RestaurantActivateView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'restaurants.activate'

    def post(self, request, pk):
        restaurant = _get_restaurants_queryset_for_request(request).get(pk=pk)
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
        if 'permissions' in validated:
            entitlement.permissions.set(validated['permissions'])
        if 'allowed_roles' in validated:
            entitlement.allowed_roles.set(validated['allowed_roles'])

        admin_username = f'rest_{restaurant.id}_admin'
        password = _generate_password()
        admin_user = restaurant.users.filter(actor_type=User.ActorType.RESTAURANT_ADMIN).order_by('created_at').first()
        if admin_user is None:
            admin_user = User.objects.create(
                username=admin_username,
                full_name=f'{restaurant.name} Admin',
                phone=restaurant.phone,
                ui_mode=User.UiMode.ADMIN,
                actor_type=User.ActorType.RESTAURANT_ADMIN,
                restaurant=restaurant,
                role=_get_restaurant_admin_role(),
                is_active=True,
            )
        else:
            admin_user.role = _get_restaurant_admin_role()
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
        restaurant = _get_restaurants_queryset_for_request(request).get(pk=pk)
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
        restaurant = _get_restaurants_queryset_for_request(request).get(pk=pk)
        admin_user = restaurant.users.filter(actor_type=User.ActorType.RESTAURANT_ADMIN).order_by('created_at').first()
        if admin_user is None:
            raise serializers.ValidationError({'detail': 'Restaurant admin user was not found.'})
        password = _generate_password()
        admin_user.set_password(password)
        admin_user.save(update_fields=['password'])
        payload = {'restaurant': restaurant, 'username': admin_user.username, 'password': password}
        return Response(RestaurantActivationResultSerializer(payload).data, status=status.HTTP_200_OK)
