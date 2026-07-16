from django.db.models import QuerySet
from rest_framework import permissions
from rest_framework.views import APIView

from apps.reporting.helpers import SummaryReportFilters
from apps.reporting.services import ReportPeriod, build_report_filter_pairs
from common.api.paginations import StandardResultsSetPagination
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_optional_request_restaurant


class AdminBaseReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_restaurant(self):
        return get_optional_request_restaurant(self.request)

    def get_period(self) -> ReportPeriod:
        return SummaryReportFilters.from_request(self.request).period

    @staticmethod
    def get_filter_pairs(
        period: ReportPeriod,
        extra_filters: list[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str]]:
        return build_report_filter_pairs(period, extra_filters)

    def resolve_filter_name(
        self,
        model,
        object_id: str,
        *,
        name_field: str = 'name',
        restaurant_lookup: str | None = 'restaurant',
    ) -> str:
        if not object_id:
            return ''
        queryset = model.objects.filter(pk=object_id)
        restaurant = self.get_restaurant()
        if restaurant is not None and restaurant_lookup:
            queryset = queryset.filter(**{restaurant_lookup: restaurant})
        return queryset.values_list(name_field, flat=True).first() or object_id


class AdminPaginatedReportView(AdminBaseReportView):
    pagination_class = StandardResultsSetPagination

    def paginate_queryset(self, queryset: QuerySet):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        self.paginator = paginator
        return page

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)
