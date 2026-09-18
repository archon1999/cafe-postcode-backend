"""Floor definitions without sales, sessions or kitchen projections."""
from django.db.models import Prefetch

from apps.floor.api.admin.serializers import HallSerializer
from apps.floor.api.admin.serializers.dining_table import DiningTableSerializer
from apps.floor.models import DiningTable, Hall


class FloorTableConfigurationSerializer(DiningTableSerializer):
    class Meta(DiningTableSerializer.Meta):
        fields = tuple(field for field in DiningTableSerializer.Meta.fields if field not in {
            'active_session', 'active_sessions', 'active_session_count',
            'occupied_guest_count', 'available_seat_count',
        })

    def to_representation(self, instance):
        result = super().to_representation(instance)
        # Occupancy comes from the Agent's sessions, never from configuration.
        if result['status'] == DiningTable.Status.OCCUPIED:
            result['status'] = DiningTable.Status.AVAILABLE
        return result


class FloorConfigurationSerializer(HallSerializer):
    tables = FloorTableConfigurationSerializer(many=True, read_only=True)


def floor_configuration_snapshot(restaurant):
    halls = Hall.objects.filter(zone_or_cabin__restaurant=restaurant, is_active=True).select_related(
        'zone_or_cabin', 'zone_or_cabin__restaurant',
    ).prefetch_related(Prefetch('tables', queryset=DiningTable.objects.select_related('zone')))
    return FloorConfigurationSerializer(halls.order_by('sort_order', 'name'), many=True).data
