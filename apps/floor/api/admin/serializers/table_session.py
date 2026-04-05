from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import TableSession


class TableSessionSerializer(serializers.ModelSerializer):
    hall_name = serializers.CharField(source='hall.name', read_only=True)
    table_name = serializers.CharField(source='table.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    assigned_waiter_name = serializers.CharField(source='assigned_waiter.full_name', read_only=True)

    class Meta:
        model = TableSession
        fields = (
            'id',
            'hall',
            'hall_name',
            'table',
            'table_name',
            'opened_by',
            'opened_by_name',
            'assigned_waiter',
            'assigned_waiter_name',
            'guest_count',
            'status',
            'note',
            'merged_into',
            'closed_at',
            'created_at',
        )

    def validate(self, attrs):
        hall = attrs.get('hall') or getattr(self.instance, 'hall', None)
        table = attrs.get('table') or getattr(self.instance, 'table', None)

        if hall and table and table.hall_id != hall.id:
            raise serializers.ValidationError({'table': _('Selected table does not belong to the selected hall.')})

        return attrs
