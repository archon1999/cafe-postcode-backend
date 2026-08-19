from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.models import DiningTable
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class DiningTableReserveView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)
        table = DiningTable.objects.select_for_update(of=('self',)).filter(
            pk=pk,
            hall__zone_or_cabin__restaurant=restaurant,
        ).first()
        if table is None:
            return Response({'detail': 'Table was not found.'}, status=status.HTTP_404_NOT_FOUND)

        if table.status == DiningTable.Status.RESERVED:
            return Response({'id': str(table.id), 'status': table.status}, status=status.HTTP_200_OK)

        if table.status != DiningTable.Status.AVAILABLE:
            return Response({'detail': 'Only available tables can be reserved.'}, status=status.HTTP_400_BAD_REQUEST)

        table.status = DiningTable.Status.RESERVED
        table.save(update_fields=['status', 'updated_at'])
        return Response({'id': str(table.id), 'status': table.status}, status=status.HTTP_200_OK)
