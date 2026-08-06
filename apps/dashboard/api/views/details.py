from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.api.serializers.overview import (
    DashboardCashShiftSerializer,
    DashboardOpenCheckSerializer,
    DashboardStaffSerializer,
    DashboardTopItemSerializer,
)
from apps.dashboard.services import OwnerDashboardDetailService, get_dashboard_restaurant_scope
from apps.platform.services import FeatureGateService
from apps.reporting.services import get_report_period
from common.api.paginations import StandardResultsSetPagination
from common.api.permissions import require_any_permission_code


class DashboardBaseView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    feature_gate_service_class = FeatureGateService
    detail_service_class = OwnerDashboardDetailService

    def get_restaurant(self):
        require_any_permission_code(self.request.user, 'dashboard.view')
        scope = get_dashboard_restaurant_scope(self.request)
        for restaurant in scope.restaurants:
            self.feature_gate_service_class().ensure_owner_dashboard_access(restaurant=restaurant)
        return scope.query_scope

    def get_period(self):
        return get_report_period(self.request.query_params)

    def get_service(self):
        return self.detail_service_class()


class DashboardPaginatedView(DashboardBaseView):
    pagination_class = StandardResultsSetPagination

    def paginate_queryset(self, data):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(data, self.request, view=self)
        self.paginator = paginator
        return page

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


class DashboardOpenChecksView(DashboardPaginatedView):
    def get(self, request):
        rows = self.get_service().build_open_checks_rows(
            self.get_restaurant(),
            self.get_period(),
        )
        page = self.paginate_queryset(rows)
        serializer = DashboardOpenCheckSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class DashboardTopItemsView(DashboardPaginatedView):
    def get(self, request):
        rows = self.get_service().build_top_items(
            self.get_restaurant(),
            self.get_period(),
        )
        page = self.paginate_queryset(rows)
        serializer = DashboardTopItemSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class DashboardStaffView(DashboardPaginatedView):
    def get(self, request):
        role = request.query_params.get('role') or request.query_params.get('staff_role') or 'waiter'
        if role not in {'waiter', 'cashier', 'manager'}:
            role = 'waiter'

        rows = self.get_service().get_role_breakdown_rows(
            self.get_restaurant(),
            self.get_period(),
            role=role,
        )
        page = self.paginate_queryset(rows)
        serializer = DashboardStaffSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class DashboardShiftView(DashboardPaginatedView):
    def get(self, request):
        rows = self.get_service().build_shift_rows(
            self.get_restaurant(),
            self.get_period(),
        )
        page = self.paginate_queryset(rows)
        serializer = DashboardCashShiftSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
