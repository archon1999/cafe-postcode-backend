from rest_framework import serializers

from apps.sales.helpers import get_order_item_note_model

OrderItemNote = get_order_item_note_model()


class OrderItemNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItemNote
        fields = ('id', 'body', 'created_at')
