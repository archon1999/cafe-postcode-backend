from rest_framework import serializers

from apps.kitchen.models import KitchenTicket
from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()


class KitchenMonitorQuerySerializer(serializers.Serializer):
    restaurant_id = serializers.UUIDField()

    def validate(self, attrs):
        restaurant = Restaurant.objects.filter(pk=attrs['restaurant_id'], is_active=True).first()
        if restaurant is None:
            raise serializers.ValidationError({'restaurant_id': 'Restaurant is invalid.'})

        attrs['restaurant'] = restaurant
        return attrs


class KitchenMonitorTicketSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)

    class Meta:
        model = KitchenTicket
        fields = (
            'id',
            'order_number',
            'status',
            'completed_at',
        )


class KitchenMonitorQueueSerializer(serializers.Serializer):
    preparing = KitchenMonitorTicketSerializer(many=True)
    recently_done = KitchenMonitorTicketSerializer(many=True)
