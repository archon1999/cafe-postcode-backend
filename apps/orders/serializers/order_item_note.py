from rest_framework import serializers

from apps.orders.models import OrderItemNote


class OrderItemNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItemNote
        fields = ('id', 'body', 'created_at')
