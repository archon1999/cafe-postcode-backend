from rest_framework import serializers


class TableTransferSerializer(serializers.Serializer):
    target_table_id = serializers.UUIDField()
    target_session_id = serializers.UUIDField(required=False, allow_null=True)
    expected_target_session_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )


class TableGroupSerializer(serializers.Serializer):
    table_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )

    def validate_table_ids(self, value):
        return list(dict.fromkeys(value))


class TableUngroupSerializer(serializers.Serializer):
    table_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
    )
