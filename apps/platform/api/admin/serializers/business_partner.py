from rest_framework import serializers

from apps.platform.helpers import get_business_partner_model

BusinessPartner = get_business_partner_model()


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
            'restaurants',
            'restaurants_count',
        )

    def create(self, validated_data):
        faktura_payload = _restore_faktura_payload(validated_data.pop('faktura_payload', {}))
        return BusinessPartner.objects.create(faktura_payload=faktura_payload, **validated_data)

    def update(self, instance, validated_data):
        faktura_payload = validated_data.pop('faktura_payload', serializers.empty)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if faktura_payload is not serializers.empty:
            instance.faktura_payload = _restore_faktura_payload(faktura_payload)

        instance.save()
        return instance

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

        password = attrs['password']
        if not password.strip():
            errors['password'] = 'This field may not be blank.'

        partner = self.context['partner']
        owner_user = partner.owner_user
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
