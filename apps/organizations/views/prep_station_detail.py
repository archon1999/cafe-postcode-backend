from rest_framework import generics, permissions

from apps.organizations.models import PrepStation
from apps.organizations.serializers import PrepStationSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class PrepStationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = PrepStationSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return PrepStation.objects.filter(restaurant=restaurant)
