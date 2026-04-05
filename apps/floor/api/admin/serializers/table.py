from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession

from apps.floor.serializers.active_session_summary import ActiveSessionSummarySerializer


class DiningTableSerializer(serializers.ModelSerializer):
    active_session = serializers.SerializerMethodField()
    hall_name = serializers.CharField(source='hall.name', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model = DiningTable
        fields = (
            'id',
            'hall',
            'hall_name',
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
        )

    def get_active_session(self, obj):
        prefetched_sessions = getattr(obj, '_prefetched_objects_cache', {}).get('table_sessions')
        if prefetched_sessions is None:
            session = (
                obj.table_sessions.filter(status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT])
                .order_by('-created_at')
                .first()
            )
        else:
            active_sessions = [
                session
                for session in prefetched_sessions
                if session.status in [TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT]
            ]
            session = max(active_sessions, key=lambda item: item.created_at, default=None)

        if session is None:
            return None
        return ActiveSessionSummarySerializer(session).data

    def validate_seat_count(self, value):
        if value not in DiningTable.get_supported_seat_counts():
            raise serializers.ValidationError(_('Only 2, 3, 4, 5, or 6 seat tables are supported.'))
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
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
