from django.db.models import Max
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers.mxik import (
    CatalogCategorySerializerMixin,
    MxikCodeValidationMixin,
)
from apps.catalog.utils.cash_sale import is_catalog_category_cash_sale_forbidden
from apps.restaurants.helpers import get_prep_station_model
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

PrepStation = get_prep_station_model()


class CatalogCategorySerializer(
    CatalogCategorySerializerMixin, MxikCodeValidationMixin, serializers.ModelSerializer
):
    mxik_required = True
    restaurant_id = serializers.UUIDField(source="restaurant.id", read_only=True)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    cash_payment_forbidden = serializers.SerializerMethodField()
    prep_station_name = serializers.CharField(
        source="prep_station.name", read_only=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            if getattr(request.user, "is_superuser", False):
                return
            self.fields["prep_station"].queryset = PrepStation.objects.none()
            return

        self.fields["prep_station"].queryset = PrepStation.objects.filter(
            restaurant=restaurant
        )

    def get_cash_payment_forbidden(self, obj):
        return is_catalog_category_cash_sale_forbidden(obj)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if request is not None:
            restaurant = get_request_restaurant(request)
            prep_station = attrs.get("prep_station")
            if prep_station is not None and prep_station.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {
                        "prep_station": _(
                            "Selected prep station does not belong to the current restaurant."
                        )
                    }
                )
        return attrs

    def create(self, validated_data):
        if "sort_order" not in validated_data:
            restaurant = validated_data.get("restaurant")
            current_max = CatalogCategory.objects.filter(
                restaurant=restaurant
            ).aggregate(value=Max("sort_order"))["value"]
            validated_data["sort_order"] = (
                current_max if current_max is not None else -1
            ) + 1
        return super().create(validated_data)

    class Meta:
        model = CatalogCategory
        fields = (
            "id",
            "restaurant_id",
            "restaurant_name",
            "name",
            "name_uz",
            "name_uz_crl",
            "name_ru",
            "mxik_code",
            "mxik_name",
            "mxik_payload",
            "image_url",
            "image_source",
            "image_file",
            "clear_image",
            "restore_mxik_image",
            "prep_station",
            "prep_station_name",
            "cash_payment_forbidden",
            "sort_order",
            "is_active",
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
