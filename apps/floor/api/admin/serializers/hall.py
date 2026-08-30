from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from django.db.models import Max
from rest_framework import serializers

from apps.floor.models import Hall, ZoneOrCabin
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant
from common.service_fees import validate_service_fee_configuration

from .dining_table import DiningTableSerializer
from .zone_or_cabin import ZoneOrCabinSerializer


class HallSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(
        source="zone_or_cabin.restaurant.name", read_only=True
    )
    tables = DiningTableSerializer(many=True, read_only=True)
    zone_or_cabin = ZoneOrCabinSerializer(read_only=True)
    zone_or_cabin_id = serializers.PrimaryKeyRelatedField(
        source="zone_or_cabin",
        queryset=ZoneOrCabin.objects.all(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        restaurant = (
            get_optional_request_restaurant(request) if request is not None else None
        )
        if request is None:
            return
        if restaurant is None and getattr(request.user, "is_superuser", False):
            return
        self.fields["zone_or_cabin_id"].queryset = (
            ZoneOrCabin.objects.filter(restaurant=restaurant)
            if restaurant is not None
            else ZoneOrCabin.objects.none()
        )

    class Meta:
        model = Hall
        fields = (
            "id",
            "restaurant_name",
            "name",
            "description",
            "grid_columns",
            "service_fee_enabled",
            "service_fee_mode",
            "service_fee_percent",
            "service_fee_hourly_rate",
            "sort_order",
            "is_active",
            "zone_or_cabin_id",
            "zone_or_cabin",
            "tables",
        )
        validators = []

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            if "zone_or_cabin_id" not in exc.detail:
                raise
            detail = dict(exc.detail)
            detail.pop("zone_or_cabin_id")
            detail["zoneOrCabinId"] = [_("Invalid zone or cabin.")]
            raise serializers.ValidationError(detail) from None

    def validate_service_fee_percent(self, value):
        if value < Decimal("0") or value > Decimal("99"):
            raise serializers.ValidationError(
                _("Service fee percent must be between 0 and 99.")
            )
        return value

    def validate(self, attrs):
        service_fee_errors = validate_service_fee_configuration(
            enabled=attrs.get("service_fee_enabled", getattr(self.instance, "service_fee_enabled", False)),
            mode=attrs.get("service_fee_mode", getattr(self.instance, "service_fee_mode", "percentage")),
            percent=attrs.get("service_fee_percent", getattr(self.instance, "service_fee_percent", 0)),
            hourly_rate=attrs.get(
                "service_fee_hourly_rate",
                getattr(self.instance, "service_fee_hourly_rate", 0),
            ),
        )
        if service_fee_errors:
            raise serializers.ValidationError(service_fee_errors)
        zone_or_cabin = attrs.get("zone_or_cabin")
        if zone_or_cabin is None:
            return attrs

        request = self.context.get("request")
        if request is not None:
            restaurant = get_request_restaurant(request)
            if zone_or_cabin.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {
                        "zoneOrCabinId": _(
                            "Selected zone does not belong to this restaurant."
                        )
                    }
                )

        if self.instance is None:
            return attrs

        if (
            zone_or_cabin.pk != self.instance.zone_or_cabin_id
            and self.instance.tables.exists()
        ):
            raise serializers.ValidationError(
                {"zoneOrCabinId": _("Hall zone cannot be changed while tables exist.")}
            )
        return attrs

    def create(self, validated_data):
        if "sort_order" not in validated_data:
            zone_or_cabin = validated_data["zone_or_cabin"]
            current_max = Hall.objects.filter(zone_or_cabin=zone_or_cabin).aggregate(
                value=Max("sort_order")
            )["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        return super().create(validated_data)

    def update(self, instance, validated_data):
        next_zone = validated_data.get("zone_or_cabin", instance.zone_or_cabin)
        if "sort_order" not in validated_data and next_zone != instance.zone_or_cabin:
            current_max = Hall.objects.filter(zone_or_cabin=next_zone).aggregate(
                value=Max("sort_order")
            )["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        return super().update(instance, validated_data)
