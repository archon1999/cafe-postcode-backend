from django.db.models import Max
from rest_framework import serializers

from apps.floor.models import ZoneOrCabin


class ZoneOrCabinSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)

    def create(self, validated_data):
        if "sort_order" not in validated_data:
            restaurant = validated_data.get("restaurant")
            current_max = ZoneOrCabin.objects.filter(restaurant=restaurant).aggregate(
                value=Max("sort_order")
            )["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        return super().create(validated_data)

    class Meta:
        model = ZoneOrCabin
        fields = ("id", "restaurant_name", "name", "sort_order", "is_active")
