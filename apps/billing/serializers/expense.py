from rest_framework import serializers

from apps.billing.helpers import get_cash_expense_model, get_expense_category_model

CashExpense = get_cash_expense_model()
ExpenseCategory = get_expense_category_model()


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ('id', 'name', 'is_active', 'sort_order', 'created_at', 'updated_at')
        read_only_fields = fields


class CashExpenseSerializer(serializers.ModelSerializer):
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
    cash_shift_id = serializers.UUIDField(read_only=True)
    category_name = serializers.CharField(source='category_name_snapshot', read_only=True)
    recipient_name = serializers.CharField(source='recipient_name_snapshot', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    voided_by_name = serializers.CharField(source='voided_by.full_name', read_only=True, allow_null=True)

    class Meta:
        model = CashExpense
        fields = (
            'id',
            'cash_shift_id',
            'cash_desk',
            'cash_desk_name',
            'category',
            'category_name',
            'amount',
            'comment',
            'recipient',
            'recipient_name',
            'created_by',
            'created_by_name',
            'status',
            'occurred_at',
            'voided_at',
            'voided_by',
            'voided_by_name',
            'void_reason',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class CashExpenseCreateSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    amount = serializers.IntegerField(min_value=1)
    category_id = serializers.UUIDField()
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)
    recipient_id = serializers.UUIDField(required=False, allow_null=True)
    cash_shift_id = serializers.UUIDField(required=False, allow_null=True)
    edge_operation_id = serializers.CharField(required=False, allow_blank=True, max_length=128)


class CashExpenseVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
