from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.services.marking import serialize_catalog_scan
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosCatalogScanView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request):
        restaurant = get_request_restaurant(request)
        raw_code = request.data.get('raw_code') or request.data.get('rawCode') or ''
        return Response(serialize_catalog_scan(restaurant=restaurant, raw_code=raw_code), status=status.HTTP_200_OK)
