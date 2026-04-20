from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integrations.api.admin.serializers import FiscalDeviceDiscoveryQuerySerializer, FiscalDeviceSerializer
from apps.integrations.services.fiscal_drive import FiscalDriveError, discover_fiscal_devices
from common.api.permissions import EndpointRBACPermission


class FiscalDeviceListView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        serializer = FiscalDeviceDiscoveryQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        endpoint_url = serializer.validated_data.get('endpoint_url') or None
        try:
            devices = discover_fiscal_devices(endpoint_url=endpoint_url)
        except FiscalDriveError as error:
            return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(FiscalDeviceSerializer(devices, many=True).data, status=status.HTTP_200_OK)
