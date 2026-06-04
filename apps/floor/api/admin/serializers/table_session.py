from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession
from apps.floor.services import available_seat_count


def get_supported_seat_count(seat_count: int) -> int:
    if seat_count <= 2:
        return 2
    if seat_count == 3:
        return 3
    return 4


class TableSessionSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source='table.name', read_only=True)
    hall_name = serializers.CharField(source='hall.name', read_only=True)

    class Meta:
        model = TableSession
        fields = (
            'id',
            'restaurant',
            'hall',
            'hall_name',
            'table',
            'table_name',
            'opened_by',
            'assigned_waiter',
            'guest_count',
            'status',
            'note',
            'merged_into',
            'closed_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('restaurant', 'hall', 'opened_by', 'closed_at', 'merged_into')

    def validate(self, attrs):
        table = attrs.get('table') or getattr(self.instance, 'table', None)
        guest_count = attrs.get('guest_count', getattr(self.instance, 'guest_count', None))
        if table is None:
            return attrs

        if table.status == DiningTable.Status.BLOCKED:
            raise serializers.ValidationError({'table': _('This table is blocked.')})

        if guest_count is not None and guest_count > int(table.seat_count or 0):
            raise serializers.ValidationError(
                {
                    'guest_count': _(
                        'Guest count cannot exceed this table limit (%(limit)s).'
                    )
                    % {'limit': int(table.seat_count or 0)}
                }
            )
        if guest_count is not None and guest_count > available_seat_count(table, exclude_session=self.instance):
            raise serializers.ValidationError(
                {
                    'guest_count': _(
                        'Guest count cannot exceed available seats on this table (%(limit)s).'
                    )
                    % {'limit': available_seat_count(table, exclude_session=self.instance)}
                }
            )
        return attrs
