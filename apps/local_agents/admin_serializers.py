from rest_framework import serializers

from apps.local_agents.models import LocalAgent


class LocalAgentFleetSerializer(serializers.ModelSerializer):
    restaurant_id = serializers.UUIDField(source='restaurant.id', read_only=True)
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)
    status = serializers.SerializerMethodField()
    online = serializers.SerializerMethodField()

    class Meta:
        model = LocalAgent
        fields = (
            'id',
            'restaurant_id',
            'restaurant_name',
            'name',
            'status',
            'online',
            'version',
            'last_seen_at',
            'capabilities',
            'lan_endpoints',
            'protocol_version',
            'rollout_state',
            'is_active',
        )

    @staticmethod
    def get_online(obj):
        return obj.is_online()

    def get_status(self, obj):
        return LocalAgent.Status.ONLINE if self.get_online(obj) else LocalAgent.Status.OFFLINE
