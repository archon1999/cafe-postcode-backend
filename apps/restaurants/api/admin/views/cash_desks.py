from rest_framework import generics

from apps.restaurants.api.admin.serializers import CashDeskSerializer
from apps.restaurants.helpers import get_cash_desk_model
from apps.restaurants.selectors.resources import CashDeskListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant

CashDesk = get_cash_desk_model()


class CashDeskListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = CashDeskSerializer

    def get_queryset(self):
        queryset = filter_queryset_by_optional_restaurant(
            CashDesk.objects.select_related(
                "restaurant",
                "fiscal_integration",
                "payment_integration",
                "printer_integration",
            ),
            self.request,
        )
        return CashDeskListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class CashDeskDetailView(
    AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = CashDeskSerializer

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            CashDesk.objects.select_related(
                "restaurant",
                "fiscal_integration",
                "payment_integration",
                "printer_integration",
            ),
            self.request,
        )


__all__ = ["CashDeskDetailView", "CashDeskListCreateView"]
