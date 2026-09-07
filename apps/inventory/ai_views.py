from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES
from common.api.permissions import require_any_permission_code
from common.api.scopes import get_request_restaurant

from .ai import analyze_inventory
from .models import Warehouse
from .services import scoped


class InventoryAIThrottle(UserRateThrottle):
    scope = 'inventory_ai'
    rate = '6/min'


class InventoryAnalysisView(APIView):
    permission_classes = ADMIN_PERMISSION_CLASSES
    throttle_classes = [InventoryAIThrottle]

    def post(self, request):
        require_any_permission_code(request.user, 'admin.inventory.view')
        require_any_permission_code(request.user, 'admin.inventory.view_cost')
        restaurant = get_request_restaurant(request)
        warehouse = None
        if request.data.get('warehouse'):
            warehouse = scoped(Warehouse, restaurant, request.data['warehouse'], 'warehouse')
        language = str(request.headers.get('Accept-Language', 'uz')).split(',')[0].strip()
        return Response(analyze_inventory(restaurant, warehouse, language))
