from django.db.models import Max
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import CatalogCategory, CatalogItem, ModifierGroup
from apps.catalog.serializers.mxik import (
    CatalogImageSerializerMixin,
    MxikCodeValidationMixin,
)
from apps.catalog.utils.marking import (
    item_marking_gtin,
    item_requires_marking,
    payload_requires_marking,
)
from apps.restaurants.helpers import get_prep_station_model
from apps.catalog.utils.prep_station import resolve_order_item_prep_station
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

PrepStation = get_prep_station_model()


class CatalogItemSerializer(
    CatalogImageSerializerMixin, MxikCodeValidationMixin, serializers.ModelSerializer
):
    restaurant_id = serializers.UUIDField(source="restaurant.id", read_only=True)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    prep_station_name = serializers.SerializerMethodField()
    requires_marking = serializers.BooleanField(required=False)
    marking_gtin = serializers.CharField(required=False, allow_blank=True)
    modifier_groups = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=ModifierGroup.objects.none()
    )
    clear_modifier_groups = serializers.BooleanField(
        write_only=True, required=False, default=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            return

        self.fields["category"].queryset = CatalogCategory.objects.filter(
            restaurant=restaurant
        )
        self.fields["prep_station"].queryset = PrepStation.objects.filter(
            restaurant=restaurant
        )
        # ``many=True`` wraps the relation in DRF's ``ManyRelatedField``.  Its
        # child relation performs each primary-key lookup, so setting a
        # queryset on the wrapper leaves the original ``objects.none()`` in
        # effect and makes every submitted modifier group look invalid.
        self.fields[
            "modifier_groups"
        ].child_relation.queryset = ModifierGroup.objects.filter(restaurant=restaurant)

    class Meta:
        model = CatalogItem
        fields = (
            "id",
            "restaurant_id",
            "restaurant_name",
            "category",
            "category_name",
            "prep_station",
            "prep_station_name",
            "name",
            "name_uz",
            "name_uz_crl",
            "name_ru",
            "mxik_code",
            "mxik_name",
            "mxik_payload",
            "requires_marking",
            "marking_gtin",
            "image_url",
            "image_source",
            "image_file",
            "clear_image",
            "restore_mxik_image",
            "description",
            "description_uz",
            "description_uz_crl",
            "description_ru",
            "price",
            "sort_order",
            "modifier_groups",
            "clear_modifier_groups",
            "is_active",
            "is_stoplisted",
        )
        extra_kwargs = {
            "mxik_code": {"required": False, "allow_blank": True},
            "mxik_name": {"required": False, "allow_blank": True},
            "mxik_payload": {"required": False},
            "image_url": {"required": False, "allow_null": True, "allow_blank": True},
            "image_source": {"required": False, "allow_blank": True},
            "image_file": {"required": False, "allow_null": True},
        }
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if request is not None:
            restaurant = get_request_restaurant(request)
            category = attrs.get("category")
            prep_station = attrs.get("prep_station")

            if category is not None and category.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {
                        "category": _(
                            "Selected category does not belong to the current restaurant."
                        )
                    }
                )

            if prep_station is not None and prep_station.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {
                        "prep_station": _(
                            "Selected prep station does not belong to the current restaurant."
                        )
                    }
                )

        payload = attrs.get("mxik_payload")
        if payload is None and self.instance is not None:
            payload = getattr(self.instance, "mxik_payload", None)
        attrs["requires_marking"] = payload_requires_marking(payload)
        if not attrs.get("marking_gtin"):
            payload_item = type(
                "PayloadItem",
                (),
                {
                    "mxik_payload": payload,
                    "marking_gtin": getattr(self.instance, "marking_gtin", "")
                    if self.instance is not None
                    else "",
                },
            )()
            derived_gtin = item_marking_gtin(payload_item)
            if derived_gtin:
                attrs["marking_gtin"] = derived_gtin
        return attrs

    def create(self, validated_data):
        validated_data.pop("clear_modifier_groups", None)
        if "sort_order" not in validated_data:
            restaurant = validated_data.get("restaurant")
            category = validated_data.get("category")
            current_max = CatalogItem.objects.filter(
                restaurant=restaurant, category=category
            ).aggregate(value=Max("sort_order"))["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        return super().create(validated_data)

    def update(self, instance, validated_data):
        clear_modifier_groups = validated_data.pop("clear_modifier_groups", False)
        next_category = validated_data.get("category", instance.category)
        if "sort_order" not in validated_data and next_category != instance.category:
            current_max = CatalogItem.objects.filter(
                restaurant=instance.restaurant,
                category=next_category,
            ).aggregate(value=Max("sort_order"))["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        instance = super().update(instance, validated_data)
        if clear_modifier_groups:
            instance.modifier_groups.clear()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["requires_marking"] = item_requires_marking(instance)
        data["marking_gtin"] = item_marking_gtin(instance)
        return data

    def get_prep_station_name(self, obj):
        station = resolve_order_item_prep_station(
            catalog_item=obj, restaurant=obj.restaurant
        )
        return station.name if station is not None else ""
