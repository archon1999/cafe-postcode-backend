from decimal import Decimal
from urllib.parse import urlparse

from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from common.api.permissions import has_permission_code
from .models import InventoryItem, Recipe, RecipeLine, StockDocument, StockDocumentLine, Supplier, Warehouse


COST_FIELDS = {'unit_cost', 'base_unit_cost', 'average_cost', 'value', 'total_value', 'variance_value',
               'tolerance_value', 'estimated_cost', 'stock_value', 'receipt_value', 'issue_value',
               'sale_cost', 'valuation_adjustment'}
COST_FIELDS.update({'purchase_value', 'previous_cost', 'latest_cost', 'cost_increase_percent'})
PRIVATE_DOCUMENT_FIELDS = {'attachment_url'}


def redact_costs(value, can_view):
    if can_view:
        return value
    if isinstance(value, dict):
        return {key: None if key in COST_FIELDS or key in PRIVATE_DOCUMENT_FIELDS else redact_costs(child, False) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_costs(child, False) for child in value]
    return value


class ScopedReferenceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        restaurant = self.context['restaurant']
        queryset = self.Meta.model.objects.filter(restaurant=restaurant)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if 'name' in attrs and queryset.filter(name__iexact=attrs['name'].strip()).exists():
            raise serializers.ValidationError({'name': _('Bu nomdagi yozuv mavjud.')})
        if 'name' in attrs:
            attrs['name'] = attrs['name'].strip()
            if not attrs['name']:
                raise serializers.ValidationError({'name': _('Nom majburiy.')})
        return attrs


class WarehouseSerializer(ScopedReferenceSerializer):
    class Meta:
        model = Warehouse
        fields = ('id', 'name', 'is_active', 'is_default', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance
        resulting_active = attrs.get('is_active', instance.is_active if instance else True)
        resulting_default = attrs.get('is_default', instance.is_default if instance else False)
        if not resulting_active:
            if resulting_default:
                raise serializers.ValidationError(_('Asosiy omborni faolsizlantirishdan oldin boshqa asosiy ombor tanlang.'))
            if instance and instance.stockbalance_set.exclude(quantity=0).exists():
                raise serializers.ValidationError(_('Qoldig‘i bor omborni faolsizlantirib bo‘lmaydi.'))
        if instance and instance.is_default and attrs.get('is_default') is False:
            raise serializers.ValidationError(_('Boshqa omborni asosiy qilib tanlang.'))
        return attrs


class ItemSerializer(ScopedReferenceSerializer):
    class Meta:
        model = InventoryItem
        fields = ('id', 'name', 'sku', 'base_unit', 'purchase_unit', 'purchase_factor', 'min_quantity',
                  'tolerance_percent', 'tolerance_quantity', 'tolerance_value', 'availability_mode',
                  'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for field in ('min_quantity', 'tolerance_percent', 'tolerance_quantity', 'tolerance_value'):
            if attrs.get(field, 0) < 0:
                raise serializers.ValidationError({field: _('Manfiy qiymat mumkin emas.')})
        if attrs.get('purchase_factor', 1) <= 0:
            raise serializers.ValidationError({'purchase_factor': _('Ko‘paytiruvchi noldan katta bo‘lishi kerak.')})
        if attrs.get('tolerance_percent', 0) > 100:
            raise serializers.ValidationError({'tolerance_percent': _('Foiz 100 dan oshmasin.')})
        if self.instance and attrs.get('base_unit', self.instance.base_unit) != self.instance.base_unit:
            if self.instance.stockdocumentline_set.exists() or RecipeLine.objects.filter(item=self.instance).exists():
                raise serializers.ValidationError({'base_unit': _('Tarixda ishlatilgan o‘lchov birligi o‘zgarmaydi.')})
        if self.instance and attrs.get('is_active') is False:
            if RecipeLine.objects.filter(item=self.instance, recipe__is_active=True).exists():
                raise serializers.ValidationError(_('Ingredient faol retseptda ishlatilgan. Avval retseptni o‘zgartiring.'))
        if attrs.get('sku'):
            queryset = InventoryItem.objects.filter(restaurant=self.context['restaurant'], sku=attrs['sku'])
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'sku': _('SKU shu restoranda mavjud.')})
        return attrs


class SupplierSerializer(ScopedReferenceSerializer):
    class Meta:
        model = Supplier
        fields = ('id', 'name', 'tax_number', 'phone', 'address', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')
        validators = []


class DocumentLineInputSerializer(serializers.Serializer):
    item = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, allow_null=True)
    unit_cost = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=0, required=False)
    input_unit = serializers.ChoiceField(choices=['base', 'purchase'], required=False)
    lot_number = serializers.CharField(max_length=100, allow_blank=True, default='')
    expires_on = serializers.DateField(allow_null=True, default=None)


class DocumentInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['opening', 'receipt', 'issue', 'supplier_return', 'customer_return', 'stocktake'])
    warehouse = serializers.UUIDField()
    supplier = serializers.UUIDField(allow_null=True, required=False)
    reference = serializers.CharField(max_length=200, allow_blank=True, required=False)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False)
    occurred_at = serializers.DateTimeField(required=False)
    attachment_url = serializers.URLField(max_length=1000, allow_blank=True, required=False)
    responsible_name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=20000, allow_blank=True, required=False)
    idempotency_key = serializers.CharField(max_length=200, allow_blank=True, required=False)
    lines = DocumentLineInputSerializer(many=True)

    def validate_attachment_url(self, value):
        if '/admin/inventory/attachments/' in value:
            from .models import InventoryAttachment
            import re
            match = re.search(r'/admin/inventory/attachments/([a-fA-F0-9-]+)/download/?$', urlparse(value).path)
            if not match or not InventoryAttachment.objects.filter(pk=match.group(1), restaurant=self.context['restaurant']).exists():
                raise serializers.ValidationError(_('Ilova shu restoranga tegishli emas.'))
        return value


class DocumentLineSerializer(serializers.ModelSerializer):
    quantity = serializers.SerializerMethodField()
    base_quantity = serializers.SerializerMethodField()
    unit_cost = serializers.SerializerMethodField()
    variance_quantity = serializers.SerializerMethodField()
    variance_value = serializers.SerializerMethodField()

    @staticmethod
    def _draft_count(obj):
        return obj.document.kind == 'stocktake' and obj.document.status == 'draft'

    def get_quantity(self, obj):
        return str(obj.quantity) if obj.count_recorded else None

    def get_base_quantity(self, obj):
        return None if self._draft_count(obj) and not obj.count_recorded else str(obj.base_quantity)

    def get_unit_cost(self, obj):
        # Draft counts snapshot quantities/revisions only. Valuation is fixed
        # atomically on posting after checking that the snapshot is still valid.
        return None if self._draft_count(obj) else str(obj.unit_cost)

    def get_variance_quantity(self, obj):
        if self._draft_count(obj):
            return str(obj.base_quantity - obj.expected_quantity) if obj.count_recorded else None
        return str(obj.variance_quantity)

    def get_variance_value(self, obj):
        return None if self._draft_count(obj) else str(obj.variance_value)

    class Meta:
        model = StockDocumentLine
        fields = ('id', 'item', 'item_name', 'base_unit', 'quantity', 'count_recorded', 'unit_cost', 'input_unit',
                  'base_quantity', 'expected_quantity', 'variance_quantity', 'variance_value', 'lot_number', 'expires_on')


class DocumentSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.name')
    supplier_name = serializers.CharField(source='supplier.name', allow_null=True, default=None)
    lines = DocumentLineSerializer(many=True)
    purchase_value = serializers.SerializerMethodField()
    valuation_adjustment = serializers.SerializerMethodField()
    consumptions = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()

    def get_total_value(self, obj):
        return None if obj.kind == 'stocktake' and obj.status == 'draft' else str(obj.total_value)

    def get_purchase_value(self, obj):
        return str(sum((line.base_quantity * line.base_unit_cost for line in obj.lines.all()), Decimal('0'))) if obj.kind in {'receipt', 'opening', 'customer_return'} else None

    def get_valuation_adjustment(self, obj):
        from django.db.models import Sum
        return str(obj.movements.aggregate(total=Sum('valuation_adjustment'))['total'] or Decimal('0'))

    def get_consumptions(self, obj):
        return [{'order_item': str(row.order_item_id), 'recipe': str(row.recipe_id), 'recipe_version': row.recipe.version,
                 'quantity': str(row.quantity), 'resolved_quantity': str(row.resolved_quantity),
                 'resolutions': [{'disposition': event.disposition, 'quantity': str(event.quantity),
                                  'created_at': event.created_at, 'created_by_name': event.created_by_name}
                                 for event in row.resolutions.all()]}
                for row in obj.orderconsumption_set.select_related('recipe').prefetch_related('resolutions')]

    class Meta:
        model = StockDocument
        fields = ('id', 'number', 'kind', 'status', 'warehouse', 'warehouse_name', 'supplier', 'supplier_name',
                  'reference', 'reason', 'occurred_at', 'posted_at', 'created_at', 'attachment_url',
                  'responsible_name', 'notes', 'created_by_name', 'posted_by_name', 'reversal_of', 'total_value',
                  'purchase_value', 'valuation_adjustment', 'consumptions', 'lines')


class RecipeLineInputSerializer(serializers.Serializer):
    item = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0.000001'))
    modifier_option = serializers.UUIDField(allow_null=True, default=None)


class RecipeInputSerializer(serializers.Serializer):
    catalog_item = serializers.UUIDField()
    name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    yield_quantity = serializers.DecimalField(max_digits=18, decimal_places=6, min_value=Decimal('0.000001'), default=1)
    trigger = serializers.ChoiceField(choices=['dispatch', 'sale'], default='dispatch')
    lines = RecipeLineInputSerializer(many=True)


class RecipeLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name')
    base_unit = serializers.CharField(source='item.base_unit')
    modifier_option_name = serializers.CharField(source='modifier_option.name', allow_null=True, default=None)

    class Meta:
        model = RecipeLine
        fields = ('id', 'item', 'item_name', 'base_unit', 'quantity', 'modifier_option', 'modifier_option_name')


class RecipeSerializer(serializers.ModelSerializer):
    catalog_item_name = serializers.CharField(source='catalog_item.name')
    lines = RecipeLineSerializer(many=True)
    estimated_cost = serializers.SerializerMethodField()

    def get_estimated_cost(self, obj):
        from .models import StockBalance
        from .services import q
        costs = {row.item_id: row.average_cost for row in StockBalance.objects.filter(warehouse__restaurant=obj.restaurant, warehouse__is_default=True)}
        return str(q(sum((line.quantity * costs.get(line.item_id, Decimal('0')) / obj.yield_quantity
                         for line in obj.lines.all() if line.modifier_option_id is None), Decimal('0'))))

    class Meta:
        model = Recipe
        fields = ('id', 'catalog_item', 'catalog_item_name', 'name', 'version', 'yield_quantity', 'trigger',
                  'is_active', 'estimated_cost', 'created_at', 'lines')
