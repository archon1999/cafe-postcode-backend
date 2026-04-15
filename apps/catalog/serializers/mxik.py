import re

from rest_framework import serializers

from apps.catalog.models import CatalogCategory

MXIK_CODE_PATTERN = re.compile(r'^\d{17}$')


class CatalogCategorySerializerMixin:
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
        if not isinstance(self, CatalogCategorySerializerMixin):
            return

        existing_image_source = getattr(self.instance, 'image_source', '')
        if self.instance is None or existing_image_source == CatalogCategory.ImageSource.MXIK_CACHE:
            attrs['image_url'] = None
            attrs['image_source'] = ''

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
