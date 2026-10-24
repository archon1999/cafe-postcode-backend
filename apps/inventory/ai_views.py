from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES
from common.api.permissions import require_any_permission_code
from common.api.scopes import get_request_restaurant

from .ai import analyze_inventory
from .ai_documents import preview_inventory_document
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
        return Response(analyze_inventory(restaurant, warehouse, language, user=request.user))


class DocumentPreviewInput(serializers.Serializer):
    text = serializers.CharField(max_length=40000, allow_blank=True, default='')
    kind = serializers.ChoiceField(choices=['auto', 'receipt', 'issue'], default='auto')
    warehouse = serializers.UUIDField(required=False, allow_null=True)


class InventoryDocumentPreviewView(APIView):
    permission_classes = ADMIN_PERMISSION_CLASSES
    throttle_classes = [InventoryAIThrottle]

    def post(self, request):
        from apps.catalog_assistant.inputs import normalize_input

        for code in ('admin.inventory.view', 'admin.inventory.manage', 'admin.inventory.analyze', 'admin.inventory.view_cost'):
            require_any_permission_code(request.user, code)
        restaurant = get_request_restaurant(request)
        if set(request.data) - {'text', 'kind', 'warehouse', 'files'}:
            raise serializers.ValidationError(_('Faqat matn, fayllar, hujjat turi va ombor yuboring.'))
        serializer = DocumentPreviewInput(data={key: value for key, value in request.data.items() if key != 'files'})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        warehouse = scoped(Warehouse, restaurant, data['warehouse'], 'warehouse', is_active=True) if data.get('warehouse') else None
        files = request.FILES.getlist('files')
        if request.data.get('files') and not files:
            raise serializers.ValidationError({'files': _('Fayllarni multipart formatida yuboring.')})
        if sum(upload.size for upload in files) > 20 * 1024 * 1024:
            raise serializers.ValidationError({'files': _('Fayllarning jami hajmi 20 MB dan oshmasin.')})
        content = normalize_input(data['text'], files)
        language = str(request.headers.get('Accept-Language', 'uz')).split(',')[0].strip()
        return Response(preview_inventory_document(restaurant, content, kind=data['kind'], warehouse=warehouse, language=language, user=request.user))
