from rest_framework import serializers

from apps.floor.models import LayoutObject


class LayoutObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayoutObject
        fields = (
            'id',
            'hall',
            'zone',
            'table',
            'kind',
            'label',
            'position_x',
            'position_y',
            'width',
            'height',
            'rotation',
            'payload',
            'sort_order',
        )
