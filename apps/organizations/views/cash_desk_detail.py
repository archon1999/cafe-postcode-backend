from rest_framework import generics, permissions

from apps.organizations.models import CashDesk
from apps.organizations.serializers import CashDeskSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class CashDeskDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CashDeskSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return CashDesk.objects.filter(restaurant=restaurant)
