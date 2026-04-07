from rest_framework import generics

from apps.kitchen.api.admin.serializers import KitchenTicketSerializer
from apps.kitchen.selectors.tickets import KitchenTicketListFilters, admin_kitchen_ticket_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class KitchenTicketListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = KitchenTicketSerializer

    def get_queryset(self):
        return KitchenTicketListFilters.from_request(self.request).apply(admin_kitchen_ticket_queryset(self.request))


class KitchenTicketDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = KitchenTicketSerializer

    def get_queryset(self):
        return admin_kitchen_ticket_queryset(self.request)


__all__ = ['KitchenTicketDetailView', 'KitchenTicketListView']
