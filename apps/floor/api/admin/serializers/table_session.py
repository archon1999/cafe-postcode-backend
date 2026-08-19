from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession
from apps.floor.services import (
    available_seat_count,
    restaurant_has_multiple_active_zones,
)
from apps.sales.helpers import get_order_model
from apps.users.helpers import get_user_model
from common.api.scopes import (
    get_optional_request_restaurant,
    get_request_restaurant,
)


Order = get_order_model()
User = get_user_model()


def get_supported_seat_count(seat_count: int) -> int:
    if seat_count <= 2:
        return 2
    if seat_count == 3:
        return 3
    return 4


class TableSessionSerializer(serializers.ModelSerializer):
    GENERIC_UPDATE_FORBIDDEN_FIELDS = (
        "id",
        "table",
        "status",
        "closed_at",
        "merged_into",
    )

    id = serializers.UUIDField(required=False)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    table_name = serializers.CharField(source="table.name", read_only=True)
    table_number = serializers.IntegerField(source="table.table_number", read_only=True)
    hall_name = serializers.CharField(source="hall.name", read_only=True)
    zone_name = serializers.CharField(source="hall.zone_or_cabin.name", read_only=True)
    show_zone_name = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()
    service_fee_components = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            if getattr(request.user, "is_superuser", False):
                return
            self.fields["table"].queryset = DiningTable.objects.none()
            self.fields["assigned_waiter"].queryset = User.objects.none()
            return
        self.fields["table"].queryset = DiningTable.objects.filter(
            hall__zone_or_cabin__restaurant=restaurant,
        )
        self.fields["assigned_waiter"].queryset = User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            is_active=True,
        ).distinct()

    def get_show_zone_name(self, obj):
        annotated_value = getattr(obj, "has_multiple_active_zones", None)
        if annotated_value is not None:
            return bool(annotated_value)
        restaurant_id = getattr(obj, "restaurant_id", None)
        cache = getattr(self, "_zone_visibility_cache", None)
        if cache is None:
            cache = self._zone_visibility_cache = {}
        if restaurant_id not in cache:
            cache[restaurant_id] = restaurant_has_multiple_active_zones(restaurant_id)
        return cache[restaurant_id]

    @staticmethod
    def get_service_fee_components(obj):
        component_specs = (
            ("restaurant", obj.restaurant, obj.restaurant.name),
            ("hall", obj.hall, obj.hall.name),
            ("table", obj.table, obj.table.name),
        )
        return [
            {
                "scope": scope,
                "source_name": source_name,
                "percent": percent,
            }
            for scope, source, source_name in component_specs
            if (percent := Order._enabled_service_fee_percent(source)) > 0
        ]

    def get_service_fee_percent(self, obj):
        return sum(
            (
                component["percent"]
                for component in self.get_service_fee_components(obj)
            ),
            0,
        )

    class Meta:
        model = TableSession
        fields = (
            "id",
            "restaurant",
            "restaurant_name",
            "hall",
            "hall_name",
            "zone_name",
            "show_zone_name",
            "service_fee_percent",
            "service_fee_components",
            "table",
            "table_name",
            "table_number",
            "opened_by",
            "assigned_waiter",
            "guest_count",
            "status",
            "note",
            "merged_into",
            "closed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "restaurant",
            "hall",
            "opened_by",
            "status",
            "closed_at",
            "merged_into",
        )

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            detail = dict(exc.detail)
            generic_errors = {
                "table": _("Invalid table."),
                "assigned_waiter": _("Invalid assigned waiter."),
            }
            changed = False
            for field_name, message in generic_errors.items():
                if field_name not in detail:
                    continue
                detail[field_name] = [message]
                changed = True
            if not changed:
                raise
            raise serializers.ValidationError(detail) from None

    def validate(self, attrs):
        if self.instance is not None:
            forbidden_update_errors = {
                field_name: _("This field can only be set during creation.")
                for field_name in self.GENERIC_UPDATE_FORBIDDEN_FIELDS
                if field_name in self.initial_data
            }
            if "table" in forbidden_update_errors:
                forbidden_update_errors["table"] = _(
                    "Use the table-session move action to change tables."
                )
            for field_name in ("status", "closed_at", "merged_into"):
                if field_name in forbidden_update_errors:
                    forbidden_update_errors[field_name] = _(
                        "Use the explicit table-session lifecycle action."
                    )
            if forbidden_update_errors:
                raise serializers.ValidationError(forbidden_update_errors)

        table = attrs.get("table") or getattr(self.instance, "table", None)
        guest_count = attrs.get(
            "guest_count", getattr(self.instance, "guest_count", None)
        )
        if table is None:
            return attrs

        request = self.context.get("request")
        if request is not None:
            restaurant = get_request_restaurant(request)
            if table.hall.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {"table": _("Selected table does not belong to this restaurant.")}
                )
            assigned_waiter = attrs.get(
                "assigned_waiter", getattr(self.instance, "assigned_waiter", None)
            )
            if (
                assigned_waiter is not None
                and getattr(assigned_waiter.get_restaurant_scope(), "id", None)
                != restaurant.id
            ):
                raise serializers.ValidationError(
                    {
                        "assigned_waiter": _(
                            "Selected waiter does not belong to this restaurant."
                        )
                    }
                )

        if table.status == DiningTable.Status.BLOCKED:
            raise serializers.ValidationError({"table": _("This table is blocked.")})

        if guest_count is not None and guest_count > int(table.seat_count or 0):
            raise serializers.ValidationError(
                {
                    "guest_count": _(
                        "Guest count cannot exceed this table limit (%(limit)s)."
                    )
                    % {"limit": int(table.seat_count or 0)}
                }
            )
        if guest_count is not None and guest_count > available_seat_count(
            table, exclude_session=self.instance
        ):
            raise serializers.ValidationError(
                {
                    "guest_count": _(
                        "Guest count cannot exceed available seats on this table (%(limit)s)."
                    )
                    % {
                        "limit": available_seat_count(
                            table, exclude_session=self.instance
                        )
                    }
                }
            )
        return attrs
