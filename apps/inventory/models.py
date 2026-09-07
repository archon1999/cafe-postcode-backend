from decimal import Decimal

from django.utils.translation import gettext as _
from django.conf import settings
from django.db import models
from django.core.files.storage import FileSystemStorage
from django.core.exceptions import ValidationError
from django.utils import timezone

from common.models import BaseModel


class Warehouse(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'name'), name='inv_warehouse_name'),
            models.UniqueConstraint(fields=('restaurant',), condition=models.Q(is_default=True), name='inv_default_warehouse'),
        ]


class InventoryItem(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=80, blank=True)
    base_unit = models.CharField(max_length=10, choices=[('g', 'g'), ('ml', 'ml'), ('piece', 'dona')])
    purchase_unit = models.CharField(max_length=30, blank=True)
    purchase_factor = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1'))
    min_quantity = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    tolerance_percent = models.DecimalField(max_digits=8, decimal_places=3, default=5)
    tolerance_quantity = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    tolerance_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    availability_mode = models.CharField(max_length=10, choices=[('off', 'Off'), ('warn', 'Warn'), ('block', 'Block')], default='warn')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'name'), name='inv_item_name'),
            models.UniqueConstraint(fields=('restaurant', 'sku'), condition=~models.Q(sku=''), name='inv_item_sku'),
            models.CheckConstraint(condition=models.Q(purchase_factor__gt=0), name='inv_item_factor_positive'),
            models.CheckConstraint(condition=models.Q(min_quantity__gte=0, tolerance_percent__gte=0, tolerance_quantity__gte=0, tolerance_value__gte=0), name='inv_item_threshold_positive'),
        ]


class Supplier(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    tax_number = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
        constraints = [models.UniqueConstraint(fields=('restaurant', 'name'), name='inv_supplier_name')]


class StockBalance(BaseModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    average_cost = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    value = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    revision = models.PositiveBigIntegerField(default=0)
    last_counted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('warehouse', 'item'), name='inv_balance_warehouse_item')]


class StockDocument(BaseModel):
    class Kind(models.TextChoices):
        OPENING = 'opening', 'Boshlang‘ich qoldiq'
        RECEIPT = 'receipt', 'Kirim'
        ISSUE = 'issue', 'Chiqim'
        SUPPLIER_RETURN = 'supplier_return', 'Yetkazib beruvchiga qaytarish'
        CUSTOMER_RETURN = 'customer_return', 'Mijozdan qaytish'
        STOCKTAKE = 'stocktake', 'Inventarizatsiya'
        SALE = 'sale', 'Retsept sarfi'
        SALE_RETURN = 'sale_return', 'Sarfni qaytarish'
        REVERSAL = 'reversal', 'Bekor qiluvchi hujjat'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True)
    number = models.CharField(max_length=40)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    status = models.CharField(max_length=15, choices=[('draft', 'Draft'), ('posted', 'Posted'), ('reversed', 'Reversed')], default='draft')
    reference = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    attachment_url = models.URLField(max_length=1000, blank=True)
    responsible_name = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=200, blank=True)
    request_digest = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='+', null=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='+', null=True)
    created_by_name = models.CharField(max_length=200, blank=True)
    posted_by_name = models.CharField(max_length=200, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    reversal_of = models.OneToOneField('self', on_delete=models.PROTECT, related_name='reversal', null=True, blank=True)
    total_value = models.DecimalField(max_digits=24, decimal_places=6, default=0)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'number'), name='inv_document_number'),
            models.UniqueConstraint(fields=('restaurant', 'idempotency_key'), condition=~models.Q(idempotency_key=''), name='inv_document_idempotency'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
            if old_status in {'posted', 'reversed'}:
                permitted = self.status == 'reversed' and old_status == 'posted' and set(kwargs.get('update_fields') or []) <= {'status', 'updated_at'}
                if not permitted:
                    raise ValidationError(_('Tasdiqlangan hujjat o‘zgarmaydi.'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != 'draft':
            raise ValidationError(_('Tasdiqlangan hujjat o‘chirilmaydi.'))
        return super().delete(*args, **kwargs)


class StockDocumentLine(BaseModel):
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT, related_name='lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    item_name = models.CharField(max_length=200)
    base_unit = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    count_recorded = models.BooleanField(default=True)
    input_unit = models.CharField(max_length=10, default='base')
    unit_cost = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    base_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    base_unit_cost = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    expected_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    expected_revision = models.PositiveBigIntegerField(default=0)
    variance_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    variance_value = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    consumption_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    tolerance_percent = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    tolerance_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    tolerance_value = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    lot_number = models.CharField(max_length=100, blank=True)
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('created_at', 'id')

    def save(self, *args, **kwargs):
        if StockDocument.objects.filter(pk=self.document_id).exclude(status='draft').exists():
            raise ValidationError(_('Tasdiqlangan hujjat qatori o‘zgarmaydi.'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if StockDocument.objects.filter(pk=self.document_id).exclude(status='draft').exists():
            raise ValidationError(_('Tasdiqlangan hujjat qatori o‘chirilmaydi.'))
        return super().delete(*args, **kwargs)


class StockMovement(BaseModel):
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT, related_name='movements')
    line = models.OneToOneField(StockDocumentLine, on_delete=models.PROTECT, related_name='movement')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=6)
    value = models.DecimalField(max_digits=24, decimal_places=6)
    valuation_adjustment = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    balance_after = models.DecimalField(max_digits=20, decimal_places=6)
    revision = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField()
    # UUID snapshots survive POS row splitting and deletion; never a cascading FK.
    order_item = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('warehouse', 'item', '-created_at'), name='inv_movement_scope_idx')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(_('Ombor harakati o‘zgarmaydi; teskari harakat yarating.'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_('Ombor harakati o‘chirilmaydi; teskari harakat yarating.'))


class Recipe(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    catalog_item = models.ForeignKey('catalog.CatalogItem', on_delete=models.PROTECT)
    name = models.CharField(max_length=200, blank=True)
    version = models.PositiveIntegerField()
    yield_quantity = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1'))
    trigger = models.CharField(max_length=15, choices=[('dispatch', 'Dispatch'), ('sale', 'Sale')], default='dispatch')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ('catalog_item__name', '-version')
        constraints = [
            models.UniqueConstraint(fields=('catalog_item', 'version'), name='inv_recipe_version'),
            models.UniqueConstraint(fields=('catalog_item',), condition=models.Q(is_active=True), name='inv_recipe_active'),
            models.CheckConstraint(condition=models.Q(yield_quantity__gt=0), name='inv_recipe_positive_yield'),
        ]


class RecipeLine(BaseModel):
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, related_name='lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    modifier_option = models.ForeignKey('catalog.ModifierOption', on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ('created_at',)
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name='inv_recipe_line_positive')]


class OrderConsumption(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    order_id = models.UUIDField()
    order_item_id = models.UUIDField(unique=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT)
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    resolved_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    components = models.JSONField(default=list)
    source_consumption = models.ForeignKey('self', on_delete=models.PROTECT, null=True)


class ConsumptionResolution(BaseModel):
    consumption = models.ForeignKey(OrderConsumption, on_delete=models.PROTECT, related_name='resolutions')
    event_key = models.CharField(max_length=200)
    disposition = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_by_name = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('consumption', 'event_key'), name='inv_resolution_event')]


def attachment_storage():
    from pathlib import Path
    return FileSystemStorage(location=Path(__file__).resolve().parents[2] / 'var' / 'inventory_attachments')


def attachment_upload_path(instance, filename):
    from pathlib import Path
    return f'{instance.restaurant_id}/{instance.pk}{Path(filename).suffix.lower()}'


class InventoryAttachment(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    file = models.FileField(storage=attachment_storage, upload_to=attachment_upload_path)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
