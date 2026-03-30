from rest_framework import serializers

from apps.floor.models import Hall

from .dining_table import DiningTableSerializer


class HallSerializer(serializers.ModelSerializer):
    tables = DiningTableSerializer(many=True, read_only=True)

    class Meta:
        model = Hall
        fields = (
            'id',
            'name',
            'description',
            'grid_columns',
            'sort_order',
            'is_active',
            'tables',
        )
        validators = []
