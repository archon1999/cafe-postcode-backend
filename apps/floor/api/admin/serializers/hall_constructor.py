from rest_framework import serializers

from apps.floor.models import DiningTable, Hall


class HallConstructorTableReadSerializer(serializers.ModelSerializer):
    position_x = serializers.IntegerField()
    position_y = serializers.IntegerField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()

    class Meta:
        model = DiningTable
        fields = (
            'id',
            'name',
            'table_number',
            'seat_count',
            'shape_variant',
            'position_x',
            'position_y',
            'width',
            'height',
            'is_active',
        )


class HallConstructorSerializer(serializers.ModelSerializer):
    hall_id = serializers.UUIDField(source='id', read_only=True)
    hall_name = serializers.CharField(source='name', read_only=True)
    tables = serializers.SerializerMethodField()

    class Meta:
        model = Hall
        fields = ('hall_id', 'hall_name', 'grid_columns', 'tables')

    def get_tables(self, obj):
        tables = sorted(obj.tables.all(), key=lambda table: (table.table_number, table.name))
        return HallConstructorTableReadSerializer(tables, many=True).data


class HallConstructorTableWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=255)
    table_number = serializers.IntegerField(min_value=1)
    seat_count = serializers.IntegerField(min_value=2, max_value=6)
    shape_variant = serializers.ChoiceField(choices=DiningTable.ShapeVariant.choices)
    position_x = serializers.IntegerField(min_value=0)
    position_y = serializers.IntegerField(min_value=0)
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    is_active = serializers.BooleanField(required=False, default=True)


class HallConstructorUpdateSerializer(serializers.Serializer):
    grid_columns = serializers.IntegerField(min_value=1, max_value=24)
    tables = HallConstructorTableWriteSerializer(many=True)
    deleted_table_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
