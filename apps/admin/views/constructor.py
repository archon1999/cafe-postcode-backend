from django.shortcuts import get_object_or_404
from rest_framework import generics

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import (
    BranchSerializer,
    CashDeskSerializer,
    DeviceSerializer,
    DiningTableSerializer,
    DistributionPointSerializer,
    FeatureConfigSerializer,
    HallSerializer,
    PrepStationSerializer,
    RestaurantSerializer,
    TableSessionSerializer,
)
from apps.admin.support import (
    AdminSuperuserRequiredMixin,
    BranchListFilters,
    CashDeskListFilters,
    DeviceListFilters,
    DiningTableListFilters,
    DistributionPointListFilters,
    FeatureConfigListFilters,
    HallListFilters,
    PrepStationListFilters,
    RestaurantListFilters,
    TableSessionListFilters,
    filter_constructor_queryset_by_restaurant,
)
from apps.floor.models import DiningTable, Hall, TableSession
from apps.organizations.models import Branch, CashDesk, Device, DistributionPoint, FeatureConfig, PrepStation, Restaurant
from common.api.scopes import get_request_restaurant


def get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.prefetch_related('branches', 'feature_config').select_related('business_partner').order_by('name')
    if request.user.is_superuser or request.user.has_permission_code('partners.view') or request.user.has_permission_code('partners.manage'):
        return queryset

    business_partner = request.user.get_business_partner_scope()
    if business_partner is not None:
        return queryset.filter(business_partner=business_partner)

    restaurant = request.user.get_restaurant_scope()
    if restaurant is not None:
        return queryset.filter(pk=restaurant.id)

    return queryset.none()


class RestaurantConfigView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = RestaurantSerializer
    permission_code = 'constructor.manage'

    def get_object(self):
        return get_request_restaurant(self.request)


class FeatureConfigView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = FeatureConfigSerializer
    permission_code = 'constructor.manage'

    def get_object(self):
        restaurant = get_request_restaurant(self.request)
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        return feature_config


class BranchListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = BranchSerializer
    permission_code = 'constructor.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(Branch.objects.select_related('restaurant'), self.request)
        return BranchListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class BranchDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BranchSerializer
    permission_code = 'constructor.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(Branch.objects.select_related('restaurant'), self.request)


class FeatureConfigListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = FeatureConfigSerializer
    permission_code = 'constructor.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(FeatureConfig.objects.select_related('restaurant'), self.request)
        return FeatureConfigListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class FeatureConfigDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FeatureConfigSerializer
    permission_code = 'constructor.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(FeatureConfig.objects.select_related('restaurant'), self.request)


class HallListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = HallSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'hall.manage'

    def get_queryset(self):
        queryset = (
            Hall.objects.all()
            .select_related('branch')
            .prefetch_related('tables__table_sessions')
        )
        queryset = filter_constructor_queryset_by_restaurant(queryset, self.request)
        return HallListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class HallDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = HallSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'hall.manage'

    def get_queryset(self):
        return (
            filter_constructor_queryset_by_restaurant(Hall.objects.all(), self.request)
            .select_related('branch')
            .prefetch_related('tables__table_sessions')
        )


class DiningTableListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DiningTableSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'table.manage'

    def get_queryset(self):
        queryset = (
            DiningTable.objects.all()
            .select_related('hall', 'zone')
            .prefetch_related('table_sessions')
        )
        queryset = filter_constructor_queryset_by_restaurant(queryset, self.request, 'hall__restaurant')
        return DiningTableListFilters.from_request(self.request).apply(queryset)


class DiningTableDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DiningTableSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'table.manage'

    def get_queryset(self):
        return (
            filter_constructor_queryset_by_restaurant(DiningTable.objects.all(), self.request, 'hall__restaurant')
            .select_related('hall', 'zone')
            .prefetch_related('table_sessions')
        )


class PrepStationListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = PrepStationSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(PrepStation.objects.all(), self.request)
        return PrepStationListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class PrepStationDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PrepStationSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(PrepStation.objects.all(), self.request)


class CashDeskListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = CashDeskSerializer
    permission_code = 'cashdesk.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(CashDesk.objects.all(), self.request)
        return CashDeskListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class CashDeskDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CashDeskSerializer
    permission_code = 'cashdesk.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(CashDesk.objects.all(), self.request)


class DistributionPointListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DistributionPointSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(DistributionPoint.objects.all(), self.request)
        return DistributionPointListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class DistributionPointDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DistributionPointSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(DistributionPoint.objects.all(), self.request)


class TableSessionListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = TableSessionSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'table.manage'

    def get_queryset(self):
        queryset = (
            TableSession.objects.all()
            .select_related('branch', 'hall', 'table', 'opened_by', 'assigned_waiter', 'merged_into')
        )
        queryset = filter_constructor_queryset_by_restaurant(queryset, self.request)
        return TableSessionListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        hall = serializer.validated_data['hall']
        serializer.save(restaurant=get_request_restaurant(self.request), branch=hall.branch)


class TableSessionDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TableSessionSerializer

    def get_permission_code(self):
        return 'hall.view' if self.request.method == 'GET' else 'table.manage'

    def get_queryset(self):
        return (
            filter_constructor_queryset_by_restaurant(TableSession.objects.all(), self.request)
            .select_related('branch', 'hall', 'table', 'opened_by', 'assigned_waiter', 'merged_into')
        )


class DeviceListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DeviceSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        queryset = filter_constructor_queryset_by_restaurant(
            Device.objects.select_related('branch', 'primary_hall').prefetch_related('allowed_halls'),
            self.request,
        )
        return DeviceListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class DeviceDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DeviceSerializer
    permission_code = 'integrations.manage'

    def get_queryset(self):
        return filter_constructor_queryset_by_restaurant(
            Device.objects.select_related('branch', 'primary_hall').prefetch_related('allowed_halls'),
            self.request,
        )


class RestaurantListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RestaurantSerializer

    def get_permission_code(self):
        return 'restaurants.view' if self.request.method == 'GET' else 'restaurants.manage'

    def get_queryset(self):
        queryset = get_restaurants_queryset_for_request(self.request)
        return RestaurantListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        business_partner = self.request.user.get_business_partner_scope()
        serializer.save(business_partner=business_partner)


class RestaurantDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantSerializer

    def get_permission_code(self):
        return 'restaurants.view' if self.request.method == 'GET' else 'restaurants.manage'

    def get_queryset(self):
        return get_restaurants_queryset_for_request(self.request)


class RestaurantFeatureConfigView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = FeatureConfigSerializer
    permission_code = 'restaurants.manage'

    def get_restaurant(self):
        return get_object_or_404(get_restaurants_queryset_for_request(self.request), pk=self.kwargs['restaurant_id'])

    def get_object(self):
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=self.get_restaurant())
        return feature_config

    def perform_update(self, serializer):
        serializer.save(restaurant=self.get_restaurant())
