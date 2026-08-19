from rest_framework import serializers


class CatalogNameTranslationSerializer(serializers.Serializer):
    name_uz = serializers.CharField(required=False, allow_blank=True, max_length=255)
    name_uz_crl = serializers.CharField(required=False, allow_blank=True, max_length=255)
    name_ru = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        filled_count = sum(
            bool(str(attrs.get(field) or "").strip())
            for field in ("name_uz", "name_uz_crl", "name_ru")
        )
        if filled_count != 1:
            raise serializers.ValidationError(
                "Tarjima uchun aynan bitta tildagi nom to‘ldirilishi kerak."
            )
        return attrs
