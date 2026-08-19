from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.platform.helpers import get_business_partner_model
from apps.users.helpers import get_permission_model

BusinessPartner = get_business_partner_model()
Permission = get_permission_model()
CUSTOM_TARIFF_PERMISSION_CODE = 'restaurants.custom_tariff'


def _restore_faktura_payload(value):
    if isinstance(value, list):
        return [_restore_faktura_payload(item) for item in value]

    if not isinstance(value, dict):
        return value

    restored = {}
    for key, item in value.items():
        restored_key = key
        if isinstance(key, str) and key.startswith('_'):
            restored_key = ''.join(part.capitalize() for part in key[1:].split('_') if part)
        restored[restored_key] = _restore_faktura_payload(item)
    return restored


class BusinessPartnerSerializer(serializers.ModelSerializer):
    owner_user_id = serializers.UUIDField(read_only=True)
    faktura_payload = serializers.JSONField(required=False)
    restaurants = serializers.SerializerMethodField()
    restaurants_count = serializers.SerializerMethodField()
    custom_tariff_allowed = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = BusinessPartner
        fields = (
            'id',
            'inn',
            'company_name',
            'legal_name',
            'director_name',
            'phone',
            'email',
            'address',
            'status',
            'owner_user_id',
            'activated_at',
            'deactivated_at',
            'faktura_payload',
            'custom_tariff_allowed',
            'restaurants',
            'restaurants_count',
        )

    def create(self, validated_data):
        faktura_payload = _restore_faktura_payload(validated_data.pop('faktura_payload', {}))
        custom_tariff_allowed = validated_data.pop('custom_tariff_allowed', False)
        instance = BusinessPartner.objects.create(faktura_payload=faktura_payload, **validated_data)
        self._set_custom_tariff_permission(instance, custom_tariff_allowed)
        return instance

    def update(self, instance, validated_data):
        faktura_payload = validated_data.pop('faktura_payload', serializers.empty)
        custom_tariff_allowed = validated_data.pop('custom_tariff_allowed', serializers.empty)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if faktura_payload is not serializers.empty:
            instance.faktura_payload = _restore_faktura_payload(faktura_payload)

        instance.save()
        if custom_tariff_allowed is not serializers.empty:
            self._set_custom_tariff_permission(instance, custom_tariff_allowed)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['custom_tariff_allowed'] = instance.extra_permissions.filter(code=CUSTOM_TARIFF_PERMISSION_CODE).exists()
        return data

    @staticmethod
    def _set_custom_tariff_permission(instance, enabled):
        permission = Permission.objects.filter(code=CUSTOM_TARIFF_PERMISSION_CODE).first()
        if permission is None:
            return

        if enabled:
            instance.extra_permissions.add(permission)
        else:
            instance.extra_permissions.remove(permission)

    def get_restaurants(self, instance):
        return [
            {
                'id': restaurant.id,
                'name': restaurant.name,
            }
            for restaurant in instance.restaurants.all()
        ]

    def get_restaurants_count(self, instance):
        return len(instance.restaurants.all())


class BusinessPartnerLookupSerializer(serializers.Serializer):
    inn = serializers.CharField()
    company_name = serializers.CharField(source='companyName')
    legal_name = serializers.CharField(source='legalName')
    director_name = serializers.CharField(source='directorName', allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    faktura_payload = serializers.JSONField()


class PartnerActivationDefaultsSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class PartnerActivationSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    def validate(self, attrs):
        username_provided = 'username' in attrs
        password_provided = 'password' in attrs

        if not username_provided and not password_provided:
            return attrs

        errors = {}

        if not username_provided:
            errors['username'] = 'This field is required.'
        if not password_provided:
            errors['password'] = 'This field is required.'
        if errors:
            raise serializers.ValidationError(errors)

        username = attrs['username'].strip()
        if not username:
            errors['username'] = 'This field may not be blank.'

        partner = self.context['partner']
        owner_user = partner.owner_user
        password = attrs['password']
        if not password.strip():
            errors['password'] = 'This field may not be blank.'
        else:
            try:
                validate_password(password, user=owner_user)
            except DjangoValidationError as error:
                errors['password'] = list(error.messages)

        user_queryset = self.context['user_model'].objects.all()
        if owner_user is not None:
            user_queryset = user_queryset.exclude(pk=owner_user.pk)
        if username and user_queryset.filter(username=username).exists():
            errors['username'] = 'A user with that username already exists.'

        if errors:
            raise serializers.ValidationError(errors)

        attrs['username'] = username
        return attrs


class PartnerActivationResultSerializer(serializers.Serializer):
    partner = BusinessPartnerSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()
