from rest_framework import serializers

from apps.billing.helpers import get_cash_expense_model, get_expense_category_model
from common.api.scopes import get_request_restaurant

CashExpense = get_cash_expense_model()
ExpenseCategory = get_expense_category_model()


class AdminExpenseCategorySerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        value = str(value or '').strip()
        if not value:
            raise serializers.ValidationError('Kategoriya nomi majburiy.')
        request = self.context.get('request')
        if request is not None:
            restaurant = get_request_restaurant(request)
            queryset = ExpenseCategory.objects.filter(restaurant=restaurant, name__iexact=value)
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError('Bu nomdagi kategoriya mavjud.')
        return value

    class Meta:
        model = ExpenseCategory
        fields = ('id', 'name', 'is_active', 'sort_order', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class AdminCashExpenseSerializer(serializers.ModelSerializer):
    cash_shift_id = serializers.UUIDField(read_only=True)
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
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
