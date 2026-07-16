import json

from rest_framework import serializers

from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.restaurants.helpers import get_restaurant_model

from .restaurant_mixins import (
    RestaurantEntitlementFieldsMixin,
    RestaurantSettingsFieldsMixin,
)

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
Tariff = get_tariff_model()


def _restore_faktura_payload(value):
    if isinstance(value, list):
        return [_restore_faktura_payload(item) for item in value]

    if not isinstance(value, dict):
        return value

    restored = {}
    for key, item in value.items():
        restored_key = key
        if isinstance(key, str) and key.startswith("_"):
            restored_key = "".join(
                part.capitalize() for part in key[1:].split("_") if part
            )
        restored[restored_key] = _restore_faktura_payload(item)
    return restored


class RestaurantSerializer(
    RestaurantEntitlementFieldsMixin,
    RestaurantSettingsFieldsMixin,
    serializers.ModelSerializer,
):
    tariff_id = serializers.PrimaryKeyRelatedField(
        source="tariff",
        queryset=Tariff.objects.filter(is_active=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    permission_codes = serializers.SerializerMethodField()
    role_codes = serializers.SerializerMethodField()
    faktura_payload = serializers.JSONField(required=False)

    class Meta:
        model = Restaurant
        fields = (
            "id",
            "name",
            "legal_name",
            "tax_number",
            "phone",
            "social",
            "address",
            "faktura_payload",
            "currency",
            "auth_code",
            "service_fee_enabled",
            "service_fee_percent",
            "vat_enabled",
            "vat_percent",
            "marking_check_enabled",
            "pos_auth_background_image",
            "pos_auth_background_image_url",
            "clear_pos_auth_background_image",
            "is_active",
            "activated_at",
            "deactivated_at",
            "restaurant_access_active",
            "activation_type",
            "starts_on",
            "expires_on",
            "billing_period",
            "permission_codes",
            "role_codes",
            "tariff",
            "tariff_id",
        )
        extra_kwargs = {"currency": {"required": False}}

    def get_permission_codes(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return []
        return sorted(entitlement.get_effective_permission_codes())

    def get_role_codes(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return []
        return sorted(entitlement.get_effective_role_codes())

    def validate_faktura_payload(self, value):
        if isinstance(value, str):
            if not value.strip():
                return {}
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    "Faktura payload must be valid JSON."
                ) from exc
            if not isinstance(parsed_value, dict):
                raise serializers.ValidationError("Faktura payload must be an object.")
            return parsed_value
        return value

    def _sync_entitlement(self, restaurant, tariff=serializers.empty):
        if tariff is serializers.empty:
            return

        entitlement, _ = RestaurantEntitlement.objects.get_or_create(
            restaurant=restaurant
        )
        entitlement.tariff = tariff
        entitlement.is_custom = False
        entitlement.monthly_price = tariff.monthly_price if tariff is not None else None
        entitlement.yearly_price = tariff.yearly_price if tariff is not None else None
        entitlement.save(
            update_fields=[
                "tariff",
                "is_custom",
                "monthly_price",
                "yearly_price",
                "updated_at",
            ]
        )
        entitlement.permissions.clear()
        entitlement.allowed_roles.clear()

    def create(self, validated_data):
        tariff = validated_data.pop("tariff", serializers.empty)
        validated_data.pop("clear_pos_auth_background_image", False)
        faktura_payload = _restore_faktura_payload(
            validated_data.pop("faktura_payload", {})
        )
        validated_data["currency"] = "UZS"
        restaurant = super().create(
            {**validated_data, "faktura_payload": faktura_payload}
        )
        self._sync_entitlement(restaurant, tariff)
        return restaurant

    def update(self, instance, validated_data):
        tariff = validated_data.pop("tariff", serializers.empty)
        validated_data.pop("clear_pos_auth_background_image", False)
        faktura_payload = validated_data.pop("faktura_payload", serializers.empty)
        if faktura_payload is not serializers.empty:
            validated_data["faktura_payload"] = _restore_faktura_payload(
                faktura_payload
            )
        validated_data["currency"] = "UZS"
        old_image_name, old_image_storage = self.capture_background_image(instance)
        restaurant = super().update(instance, validated_data)
        self._sync_entitlement(restaurant, tariff)
        self.delete_replaced_background_image(
            restaurant, old_image_name, old_image_storage
        )
        return restaurant


class RestaurantSelfServiceSerializer(
    RestaurantEntitlementFieldsMixin,
    RestaurantSettingsFieldsMixin,
    serializers.ModelSerializer,
):
    """Restaurant-owned settings without platform, entitlement, or Faktura write access."""

    PLATFORM_OWNED_INPUT_FIELDS = frozenset(
        {
            "business_partner",
            "business_partner_id",
            "tariff",
            "tariff_id",
            "faktura_payload",
            "auth_code",
            "currency",
            "legal_name",
            "tax_number",
            "is_active",
            "activated_at",
            "deactivated_at",
            "starts_on",
            "expires_on",
            "billing_period",
        }
    )

    class Meta:
        model = Restaurant
        fields = (
            "id",
            "name",
            "legal_name",
            "tax_number",
            "phone",
            "social",
            "address",
            "currency",
            "auth_code",
            "service_fee_enabled",
            "service_fee_percent",
            "vat_enabled",
            "vat_percent",
            "marking_check_enabled",
            "pos_auth_background_image",
            "pos_auth_background_image_url",
            "clear_pos_auth_background_image",
            "is_active",
            "activated_at",
            "deactivated_at",
            "restaurant_access_active",
            "activation_type",
            "starts_on",
            "expires_on",
            "billing_period",
            "tariff",
        )
        read_only_fields = (
            "id",
            "legal_name",
            "tax_number",
            "currency",
            "auth_code",
            "is_active",
            "activated_at",
            "deactivated_at",
        )

    def to_internal_value(self, data):
        forbidden = sorted(self.PLATFORM_OWNED_INPUT_FIELDS.intersection(data.keys()))
        if forbidden:
            raise serializers.ValidationError(
                {
                    field: "This field is managed by the platform and cannot be changed here."
                    for field in forbidden
                }
            )
        return super().to_internal_value(data)

    def update(self, instance, validated_data):
        validated_data.pop("clear_pos_auth_background_image", False)
        old_image_name, old_image_storage = self.capture_background_image(instance)
        restaurant = super().update(instance, validated_data)
        self.delete_replaced_background_image(
            restaurant, old_image_name, old_image_storage
        )
        return restaurant


class RestaurantLookupSerializer(serializers.Serializer):
    tax_number = serializers.CharField(source="taxNumber")
    name = serializers.CharField()
    legal_name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    faktura_payload = serializers.JSONField()
