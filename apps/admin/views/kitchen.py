from rest_framework import generics

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.support import AdminKitchenTicketQuerysetMixin
from apps.kitchen.serializers import KitchenTicketSerializer


class KitchenTicketListView(AdminPermissionRequiredMixin, AdminKitchenTicketQuerysetMixin, generics.ListAPIView):
    serializer_class = KitchenTicketSerializer

    def get_queryset(self):
        return self.get_filtered_kitchen_ticket_queryset()


class KitchenTicketDetailView(AdminPermissionRequiredMixin, AdminKitchenTicketQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = KitchenTicketSerializer

    def get_queryset(self):
        return self.get_kitchen_ticket_queryset()
