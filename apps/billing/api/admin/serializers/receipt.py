from rest_framework import serializers

from apps.billing.helpers import get_receipt_model

Receipt = get_receipt_model()


class AdminReceiptSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(
        source="order.restaurant.name", read_only=True
    )
    order_number = serializers.IntegerField(source="order.order_number", read_only=True)
    order_display_name = serializers.CharField(
        source="order.display_name", read_only=True
    )
    payment_method = serializers.CharField(source="payment.method", read_only=True)
    payment_amount = serializers.IntegerField(source="payment.amount", read_only=True)

    class Meta:
        model = Receipt
        fields = (
            "id",
            "restaurant_name",
            "order",
            "order_number",
            "order_display_name",
            "payment",
            "payment_method",
            "payment_amount",
            "kind",
            "status",
            "provider",
            "payload",
            "fiscal_requested_at",
            "fiscal_registered_at",
            "original_paid_at",
            "fiscal_error_code",
            "fiscal_error_message",
            "reprint_count",
            "last_reprinted_at",
            "created_at",
            "updated_at",
        )


class AdminReceiptWithPrintPreviewSerializer(AdminReceiptSerializer):
    print_document = serializers.UUIDField(source="print_document_id", read_only=True)
    print_layout = serializers.SerializerMethodField()
    print_data_snapshot = serializers.SerializerMethodField()

    def get_print_layout(self, obj):
        if not obj.print_document_id:
            return None
        return obj.print_document.template_version.layout

    def get_print_data_snapshot(self, obj):
        if not obj.print_document_id:
            return None
        return obj.print_document.data_snapshot

    class Meta(AdminReceiptSerializer.Meta):
        fields = AdminReceiptSerializer.Meta.fields + (
            "print_document",
            "print_layout",
            "print_data_snapshot",
        )
