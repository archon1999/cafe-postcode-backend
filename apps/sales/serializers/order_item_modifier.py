from rest_framework import serializers

from apps.sales.models import OrderItemModifier


class OrderItemModifierSerializer(serializers.ModelSerializer):
    option_id = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()

    class Meta:
        model = OrderItemModifier
        fields = ('id', 'option_id', 'group_id', 'group_name', 'option_name', 'price_delta', 'sort_order')

    @staticmethod
    def get_option_id(obj):
        return str(obj.modifier_option_id or '') or None

    @staticmethod
    def get_group_id(obj):
        if not obj.modifier_option_id:
            return None
        return str(obj.modifier_option.group_id)


class SelectedModifierGroupSerializer(serializers.Serializer):
    group = serializers.UUIDField()
    options = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
