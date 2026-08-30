from rest_framework import serializers
from django.utils import timezone

from apps.billing.api.admin.serializers import (
    AdminPaymentSerializer,
    AdminReceiptSerializer,
    AdminReceiptWithPrintPreviewSerializer,
)
from apps.sales.helpers import get_order_model

from .order_item import AdminOrderItemSerializer

Order = get_order_model()


class AdminOrderSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    items = AdminOrderItemSerializer(many=True, read_only=True)
    payments = AdminPaymentSerializer(many=True, read_only=True)
    receipts = AdminReceiptSerializer(many=True, read_only=True)
    table_id = serializers.UUIDField(source="table_session.table_id", read_only=True)
    table_name = serializers.CharField(
        source="table_session.table.name", read_only=True
    )
    hall_name = serializers.CharField(source="table_session.hall.name", read_only=True)
    distribution_point_name = serializers.CharField(
        source="distribution_point.name", read_only=True
    )
    opened_by_name = serializers.CharField(source="opened_by.full_name", read_only=True)
    cashier_name = serializers.CharField(source="cashier.full_name", read_only=True)
    total_overridden_by_name = serializers.CharField(
        source="total_overridden_by.full_name", read_only=True
    )
    service_fee = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()
    service_fee_components = serializers.SerializerMethodField()
    service_fee_billable_minutes = serializers.SerializerMethodField()
    calculated_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()
    payments_count = serializers.SerializerMethodField()
    receipts_count = serializers.SerializerMethodField()

    def _service_fee_as_of(self, obj):
        if obj.service_fee_frozen_at is not None:
            return obj.service_fee_frozen_at
        cache = getattr(self, "_service_fee_quote_times", None)
        if cache is None:
            cache = self._service_fee_quote_times = {}
        if obj.pk not in cache:
            cache[obj.pk] = timezone.now()
        return cache[obj.pk]

    def get_service_fee(self, obj):
        return obj.get_service_fee_amount(as_of=self._service_fee_as_of(obj))

    def get_calculated_total(self, obj):
        return obj.get_calculated_total(as_of=self._service_fee_as_of(obj))

    def get_total(self, obj):
        return obj.get_total(as_of=self._service_fee_as_of(obj))

    def get_service_fee_percent(self, obj):
        return obj.service_fee_percent

    def get_service_fee_components(self, obj):
        return obj.get_service_fee_components(as_of=self._service_fee_as_of(obj))

    def get_service_fee_billable_minutes(self, obj):
        return obj.get_service_fee_billable_minutes(as_of=self._service_fee_as_of(obj))

    def get_items_count(self, obj):
        return obj.items.count()

    def get_payments_count(self, obj):
        return obj.payments.count()

    def get_receipts_count(self, obj):
        return obj.receipts.count()

    class Meta:
        model = Order
        fields = (
            "id",
            "restaurant_name",
            "table_session",
            "table_id",
            "table_name",
            "hall_name",
            "distribution_point",
            "distribution_point_name",
            "opened_by",
            "opened_by_name",
            "cashier",
            "cashier_name",
            "order_number",
            "display_name",
            "channel",
            "status",
            "guest_count",
            "note",
            "subtotal",
            "calculated_total",
            "total_override",
            "total_override_reason",
            "total_overridden_by",
            "total_overridden_by_name",
            "total_overridden_at",
            "service_fee",
            "service_fee_percent",
            "service_fee_components",
            "service_fee_billable_minutes",
            "restaurant_service_fee_percent",
            "hall_service_fee_percent",
            "table_service_fee_percent",
            "service_fee_started_at",
            "service_fee_frozen_at",
            "total",
            "closed_at",
            "items_count",
            "payments_count",
            "receipts_count",
            "items",
            "payments",
            "receipts",
            "created_at",
            "updated_at",
        )


class AdminOrderDetailSerializer(AdminOrderSerializer):
    receipts = AdminReceiptWithPrintPreviewSerializer(many=True, read_only=True)
