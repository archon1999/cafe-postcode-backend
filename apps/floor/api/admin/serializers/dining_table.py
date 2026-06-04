from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession
from apps.floor.services import ACTIVE_SESSION_STATUSES, available_seat_count, occupied_guest_count

from .active_session_summary import ActiveSessionSummarySerializer


class DiningTableSerializer(serializers.ModelSerializer):
    active_session = serializers.SerializerMethodField()
    active_sessions = serializers.SerializerMethodField()
    active_session_count = serializers.SerializerMethodField()
    occupied_guest_count = serializers.SerializerMethodField()
    available_seat_count = serializers.SerializerMethodField()
    zone_name = serializers.SerializerMethodField()

    class Meta:
        model = DiningTable
        fields = (
            'id',
            'hall',
            'zone',
            'zone_name',
            'name',
            'table_number',
            'seat_count',
            'shape',
            'shape_variant',
            'status',
            'position_x',
            'position_y',
            'width',
            'height',
            'rotation',
            'is_active',
            'active_session',
            'active_sessions',
            'active_session_count',
            'occupied_guest_count',
            'available_seat_count',
        )

    def _active_sessions(self, obj):
        prefetched_sessions = getattr(obj, '_prefetched_objects_cache', {}).get('table_sessions')
        if prefetched_sessions is None:
            return list(
                obj.table_sessions.filter(status__in=ACTIVE_SESSION_STATUSES).order_by('-created_at')
            )
        return sorted(
            [session for session in prefetched_sessions if session.status in ACTIVE_SESSION_STATUSES],
            key=lambda item: item.created_at,
            reverse=True,
        )

    def get_active_session(self, obj):
        session = next(iter(self._active_sessions(obj)), None)
        if session is None:
            return None
        return ActiveSessionSummarySerializer(session).data

    def get_active_sessions(self, obj):
        return ActiveSessionSummarySerializer(self._active_sessions(obj), many=True).data

    def get_active_session_count(self, obj):
        return len(self._active_sessions(obj))

    def get_occupied_guest_count(self, obj):
        return occupied_guest_count(obj)

    def get_available_seat_count(self, obj):
        return available_seat_count(obj)

    def get_zone_name(self, obj):
        return getattr(getattr(obj, 'zone', None), 'name', None)

    def validate_seat_count(self, value):
        if value not in DiningTable.get_supported_seat_counts():
            raise serializers.ValidationError(_('Only 2, 3, 4, 5, or 6 seat tables are supported.'))
        return value

    def validate(self, attrs):
        hall = attrs.get('hall', getattr(self.instance, 'hall', None))

        if hall is not None:
            attrs['zone'] = hall.zone_or_cabin

        seat_count = attrs.get('seat_count', getattr(self.instance, 'seat_count', 4))
        shape_variant = attrs.get(
            'shape_variant',
            getattr(self.instance, 'shape_variant', DiningTable.get_default_shape_variant(seat_count)),
        )

        if shape_variant not in DiningTable.get_supported_variants_for_seat_count(seat_count):
            raise serializers.ValidationError({'shape_variant': _('Shape variant does not match the selected seat count.')})

        attrs['shape_variant'] = shape_variant
        if 'shape' not in attrs:
            attrs['shape'] = DiningTable.infer_shape_from_variant(shape_variant)
        return attrs
