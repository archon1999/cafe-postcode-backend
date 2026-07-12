from rest_framework import serializers

from apps.printing.models import PrintTemplate, PrintTemplateVersion
from apps.printing.presets import PRESET_PACKS
from apps.printing.services import TemplateLayoutValidationError, validate_template_layout


class PrintTemplateVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintTemplateVersion
        fields = (
            'id',
            'revision',
            'schema_version',
            'status',
            'preset_key',
            'layout',
            'created_by',
            'published_at',
            'created_at',
        )
        read_only_fields = fields


class PrintTemplateSerializer(serializers.ModelSerializer):
    published_version = PrintTemplateVersionSerializer(read_only=True)
    versions = PrintTemplateVersionSerializer(many=True, read_only=True)

    class Meta:
        model = PrintTemplate
        fields = ('id', 'kind', 'published_version', 'versions', 'created_at', 'updated_at')
        read_only_fields = fields


class PrintTemplateVersionCreateSerializer(serializers.Serializer):
    layout = serializers.JSONField(required=False)
    preset_key = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate(self, attrs):
        layout = attrs.get('layout')
        preset_key = str(attrs.get('preset_key') or '').strip()
        if layout is None and not preset_key:
            raise serializers.ValidationError('Either layout or presetKey is required.')
        valid_preset_keys = {item['key'] for item in PRESET_PACKS}
        if preset_key and preset_key not in valid_preset_keys:
            raise serializers.ValidationError({'preset_key': 'Unknown preset pack.'})
        if layout is not None:
            template = self.context['template']
            try:
                validate_template_layout(kind=template.kind, layout=layout)
            except TemplateLayoutValidationError as error:
                raise serializers.ValidationError(error.errors) from error
        attrs['preset_key'] = preset_key
        return attrs
