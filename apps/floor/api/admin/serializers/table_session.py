from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession, TableSessionTable
from apps.floor.services import (
    available_seat_count,
    restaurant_has_multiple_active_zones,
    session_physical_tables,
)
from apps.users.helpers import get_user_model
from common.api.scopes import (
    get_optional_request_restaurant,
    get_request_restaurant,
)
from common.service_fees import (
    ServiceFeeMode,
    build_service_fee_snapshot,
    normalize_service_fee_snapshot,
)


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
        "opened_at",
        "service_fee_snapshot",
        "merged_into",
    )

    id = serializers.UUIDField(required=False)
    opened_at = serializers.DateTimeField(required=False)
    service_fee_snapshot = serializers.JSONField(required=False, write_only=True)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    table_name = serializers.CharField(source="table.name", read_only=True)
    table_number = serializers.IntegerField(source="table.table_number", read_only=True)
    hall_name = serializers.CharField(source="hall.name", read_only=True)
    zone_name = serializers.CharField(source="hall.zone_or_cabin.name", read_only=True)
    show_zone_name = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()
    service_fee_components = serializers.SerializerMethodField()
    tables = serializers.SerializerMethodField()
    group_table_count = serializers.SerializerMethodField()

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
        snapshot = normalize_service_fee_snapshot(obj.service_fee_snapshot)
        if snapshot:
            return snapshot
        return build_service_fee_snapshot(
            restaurant=obj.restaurant,
            hall=obj.hall,
            table=obj.table,
        )

    def get_service_fee_percent(self, obj):
        return sum(
            (
                component["percent"]
                for component in self.get_service_fee_components(obj)
                if component["mode"] == ServiceFeeMode.PERCENTAGE
            ),
            0,
        )

    @staticmethod
    def get_tables(obj):
        return [
            {
                "id": str(table.pk),
                "name": table.name,
                "table_number": table.table_number,
                "hall_id": str(table.hall_id),
                "is_primary": table.pk == obj.table_id,
            }
            for table in session_physical_tables(obj)
        ]

    def get_group_table_count(self, obj):
        return len(self.get_tables(obj))

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
            "service_fee_snapshot",
            "table",
            "table_name",
            "table_number",
            "tables",
            "group_table_count",
            "opened_by",
            "assigned_waiter",
            "guest_count",
            "status",
            "note",
            "merged_into",
            "closed_at",
            "opened_at",
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

    def _is_trusted_edge_replay(self) -> bool:
        request = self.context.get("request")
        raw_request = getattr(request, "_request", request)
        return bool(getattr(raw_request, "trusted_edge_replay", False))

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
        trusted_edge_replay = self._is_trusted_edge_replay()
        if self.instance is None:
            if "id" in attrs and not trusted_edge_replay:
                raise serializers.ValidationError(
                    {"id": _("Table session IDs are generated by the server.")}
                )
            for field_name in ("opened_at", "service_fee_snapshot"):
                if field_name in attrs and not trusted_edge_replay:
                    raise serializers.ValidationError(
                        {field_name: _("Only a trusted local agent may set this field.")}
                    )
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

        if self.instance is None and TableSessionTable.objects.filter(
            table=table,
            released_at__isnull=True,
            session__status__in=(TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT),
        ).exists():
            raise serializers.ValidationError(
                {"table": _("This table is already part of an active table group.")}
            )

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

    def create(self, validated_data):
        snapshot_supplied = "service_fee_snapshot" in validated_data
        instance = self.Meta.model(**validated_data)
        if snapshot_supplied and self._is_trusted_edge_replay():
            instance.service_fee_snapshot = normalize_service_fee_snapshot(
                instance.service_fee_snapshot
            )
            instance._preserve_service_fee_snapshot = True
        instance.save()
        return instance
