from django.utils.translation import gettext_lazy as _
from django.db.models import Max
from rest_framework import serializers

from apps.floor.models import Hall, ZoneOrCabin
from common.api.scopes import get_request_restaurant

from .dining_table import DiningTableSerializer
from .zone_or_cabin import ZoneOrCabinSerializer


class HallSerializer(serializers.ModelSerializer):
    tables = DiningTableSerializer(many=True, read_only=True)
    zone_or_cabin = ZoneOrCabinSerializer(read_only=True)
    zone_or_cabin_id = serializers.PrimaryKeyRelatedField(
        source="zone_or_cabin",
        queryset=ZoneOrCabin.objects.all(),
    )

    class Meta:
        model = Hall
        fields = (
            "id",
            "name",
            "description",
            "grid_columns",
            "sort_order",
            "is_active",
            "zone_or_cabin_id",
            "zone_or_cabin",
            "tables",
        )
        validators = []

    def validate(self, attrs):
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
