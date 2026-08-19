from decimal import Decimal

from rest_framework import serializers

from common.api.fields import SecureImageField


class RestaurantEntitlementFieldsMixin(serializers.Serializer):
    restaurant_access_active = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()
    activation_type = serializers.SerializerMethodField()

    @staticmethod
    def _get_entitlement(instance):
        return getattr(instance, "entitlement", None)

    def get_restaurant_access_active(self, instance):
        entitlement = self._get_entitlement(instance)
        return bool(entitlement and entitlement.is_active)

    def get_tariff(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None or entitlement.tariff is None:
            return None
        tariff = entitlement.tariff
        return {
            "id": str(tariff.id),
            "name": tariff.name,
            "permission_codes": sorted(entitlement.get_effective_permission_codes()),
            "role_codes": sorted(entitlement.get_effective_role_codes()),
        }

    def get_activation_type(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return None
        return "custom" if entitlement.is_custom else "tariff"


class RestaurantSettingsFieldsMixin(serializers.Serializer):
    pos_auth_background_image = SecureImageField(
        required=False, allow_null=True, write_only=True
    )
    pos_auth_background_image_url = serializers.SerializerMethodField()
    clear_pos_auth_background_image = serializers.BooleanField(
        required=False, default=False, write_only=True
    )
    service_fee_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("99"),
        required=False,
    )

    def get_pos_auth_background_image_url(self, instance):
        image = getattr(instance, "pos_auth_background_image", None)
        if image and getattr(image, "name", ""):
            return image.url
        return None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        clear_image = attrs.get("clear_pos_auth_background_image", False)
        image = attrs.get("pos_auth_background_image")
        if clear_image and image is not None:
            raise serializers.ValidationError(
                {
                    "pos_auth_background_image": "Image upload cannot be combined with image removal."
                }
            )
        if clear_image:
            attrs["pos_auth_background_image"] = None
        return attrs

    @staticmethod
    def capture_background_image(instance):
        image = instance.pos_auth_background_image
        name = image.name if image and getattr(image, "name", "") else ""
        storage = image.storage if name else None
        return name, storage

    @staticmethod
    def delete_replaced_background_image(instance, old_name, old_storage):
        image = instance.pos_auth_background_image
        new_name = image.name if image and getattr(image, "name", "") else ""
        if old_name and old_name != new_name and old_storage is not None:
            old_storage.delete(old_name)
