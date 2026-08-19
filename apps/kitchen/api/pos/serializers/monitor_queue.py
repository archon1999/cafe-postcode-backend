from rest_framework import serializers

from apps.kitchen.models import KitchenAnnouncement, KitchenTicket
class KitchenMonitorQuerySerializer(serializers.Serializer):
    restaurant_id = serializers.UUIDField()


class KitchenMonitorTicketSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source='order.id', read_only=True)
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    display_name = serializers.CharField(source='order.display_name', read_only=True)

    class Meta:
        model = KitchenTicket
        fields = (
            'id',
            'order_id',
            'order_number',
            'display_name',
            'status',
            'completed_at',
        )


class KitchenAnnouncementSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source='order.id', read_only=True)
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)

    class Meta:
        model = KitchenAnnouncement
        fields = (
            'id',
            'order_id',
            'order_number',
            'display_name',
            'locale',
            'kind',
            'created_at',
        )


class KitchenMonitorQueueSerializer(serializers.Serializer):
    monitor_variant = serializers.CharField()
    preparing = KitchenMonitorTicketSerializer(many=True)
    recently_done = KitchenMonitorTicketSerializer(many=True)
    announcements = KitchenAnnouncementSerializer(many=True)
