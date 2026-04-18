import json
import re

from rest_framework import serializers

MXIK_CODE_PATTERN = re.compile(r'^\d{17}$')


class CatalogImageSerializerMixin(serializers.Serializer):
    image_file = serializers.ImageField(required=False, allow_null=True, write_only=True)
    clear_image = serializers.BooleanField(required=False, default=False, write_only=True)
    restore_mxik_image = serializers.BooleanField(required=False, default=False, write_only=True)

    def to_internal_value(self, data):
        if hasattr(data, 'copy'):
            data = data.copy()

        if hasattr(data, 'get'):
            if data.get('image_file') is None and data.get('imageFile') is not None:
                data['image_file'] = data.get('imageFile')
            if data.get('clear_image') is None and data.get('clearImage') is not None:
                data['clear_image'] = data.get('clearImage')
            if data.get('restore_mxik_image') is None and data.get('restoreMxikImage') is not None:
                data['restore_mxik_image'] = data.get('restoreMxikImage')

        return super().to_internal_value(data)

    @staticmethod
    def _has_image_file(image_field) -> bool:
        return bool(image_field and getattr(image_field, 'name', ''))

    def _get_effective_image_url(self, instance) -> str | None:
        image_file = getattr(instance, 'image_file', None)
        if getattr(instance, 'image_source', '') == 'manual' and self._has_image_file(image_file):
            return image_file.url
        return getattr(instance, 'image_url', None)

    def _delete_file(self, storage, image_name: str) -> None:
        if not storage or not image_name:
            return
        storage.delete(image_name)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        clear_image = attrs.get('clear_image', False)
        restore_mxik_image = attrs.get('restore_mxik_image', False)
        image_file = attrs.get('image_file')

        if clear_image and restore_mxik_image:
            raise serializers.ValidationError('Image cannot be cleared and restored at the same time.')
        if image_file is not None and clear_image:
            raise serializers.ValidationError('Image upload cannot be combined with image removal.')
        if image_file is not None and restore_mxik_image:
            raise serializers.ValidationError('Image upload cannot be combined with MXIK restore.')

        if clear_image:
            attrs['image_file'] = None
            attrs['image_url'] = None
            attrs['image_source'] = ''
        elif restore_mxik_image:
            attrs['image_file'] = None
            attrs['image_source'] = 'mxik-cache' if attrs.get('image_url') else ''
        elif image_file is not None:
            attrs['image_source'] = 'manual'

        return attrs

    def create(self, validated_data):
        validated_data.pop('clear_image', False)
        validated_data.pop('restore_mxik_image', False)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('clear_image', False)
        validated_data.pop('restore_mxik_image', False)
        old_image_field = getattr(instance, 'image_file', None)
        old_image_name = old_image_field.name if self._has_image_file(old_image_field) else ''
        old_image_storage = old_image_field.storage if old_image_name else None

        updated_instance = super().update(instance, validated_data)

        new_image = getattr(updated_instance, 'image_file', None)
        new_image_name = new_image.name if self._has_image_file(new_image) else ''
        if old_image_name and old_image_name != new_image_name:
            self._delete_file(old_image_storage, old_image_name)

        return updated_instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['image_url'] = self._get_effective_image_url(instance)
        data['image_source'] = getattr(instance, 'image_source', '') or None
        return data


class CatalogCategorySerializerMixin(CatalogImageSerializerMixin):
    pass


class MxikCodeValidationMixin(serializers.Serializer):
    mxik_required = False

    def validate_mxik_code(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            if self.mxik_required and self.instance is None:
                raise serializers.ValidationError('MXIK code is required.')
            return ''
        if not MXIK_CODE_PATTERN.fullmatch(normalized_value):
            raise serializers.ValidationError('MXIK code must contain exactly 17 digits.')
        return normalized_value

    def validate_mxik_payload(self, value):
        if value in (None, ''):
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError('MXIK payload must be valid JSON.') from exc
        if not isinstance(value, dict):
            raise serializers.ValidationError('MXIK payload must be an object.')
        return value

    @staticmethod
    def _payload_name(payload: dict) -> str:
        name = str(
            payload.get('mxikName')
            or payload.get('mxik_name')
            or payload.get('name')
            or payload.get('shortName')
            or ''
        ).strip()
        if name:
            return name

        return ' / '.join(
            filter(
                None,
                [
                    str(payload.get('subPositionName') or payload.get('sub_position_name') or '').strip(),
                    str(payload.get('positionName') or payload.get('position_name') or '').strip(),
                    str(payload.get('className') or payload.get('class_name') or '').strip(),
                ],
            )
        ).strip()

    def _clear_cached_mxik_image(self, attrs):
        if not isinstance(self, CatalogImageSerializerMixin):
            return

        existing_image = getattr(self.instance, 'image_file', None)
        has_existing_manual_image = (
            getattr(self.instance, 'image_source', '') == 'manual'
            and bool(existing_image and getattr(existing_image, 'name', ''))
        )
        has_incoming_manual_image = attrs.get('image_file') is not None

        attrs['image_url'] = None
        attrs['image_source'] = 'manual' if has_existing_manual_image or has_incoming_manual_image else ''

    def validate(self, attrs):
        attrs = super().validate(attrs)
        mxik_code_provided = 'mxik_code' in attrs
        mxik_payload_provided = 'mxik_payload' in attrs
        existing_mxik_code = getattr(self.instance, 'mxik_code', '')

        mxik_code = attrs.get('mxik_code')
        if self.instance is not None and mxik_code is None:
            mxik_code = existing_mxik_code

        mxik_name = (attrs.get('mxik_name') or '').strip()
        if self.instance is not None and not mxik_name:
            mxik_name = self.instance.mxik_name

        existing_payload = getattr(self.instance, 'mxik_payload', {}) or {}
        code_changed = self.instance is not None and mxik_code_provided and mxik_code != existing_mxik_code
        if mxik_payload_provided:
            mxik_payload = attrs.get('mxik_payload') or {}
        elif self.instance is not None and not code_changed:
            mxik_payload = existing_payload
        else:
            mxik_payload = {}

        if self.mxik_required and not mxik_code and self.instance is None:
            raise serializers.ValidationError({'mxik_code': 'MXIK code is required.'})

        if not mxik_code:
            attrs['mxik_name'] = ''
            attrs['mxik_payload'] = {}
            self._clear_cached_mxik_image(attrs)
            return attrs

        attrs['mxik_name'] = mxik_name or self._payload_name(mxik_payload)
        attrs['mxik_payload'] = mxik_payload

        if code_changed and not attrs.get('image_url'):
            self._clear_cached_mxik_image(attrs)

        return attrs
