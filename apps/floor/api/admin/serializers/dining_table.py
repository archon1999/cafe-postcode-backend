from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import DiningTable, TableSession
from apps.floor.services import ACTIVE_SESSION_STATUSES
from common.api.scopes import (
    get_optional_request_restaurant,
    get_request_restaurant,
)

from .active_session_summary import ActiveSessionSummarySerializer


PREFETCHED_ACTIVE_SESSIONS_ATTR = "serialized_active_sessions"
_SERIALIZER_ACTIVE_SESSIONS_CACHE_ATTR = "_serializer_active_sessions"
_SERIALIZER_OCCUPIED_GUEST_COUNT_CACHE_ATTR = "_serializer_occupied_guest_count"
_MISSING = object()


class DiningTableSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(
        source="hall.zone_or_cabin.restaurant.name", read_only=True
    )
    active_session = serializers.SerializerMethodField()
    active_sessions = serializers.SerializerMethodField()
    active_session_count = serializers.SerializerMethodField()
    occupied_guest_count = serializers.SerializerMethodField()
    available_seat_count = serializers.SerializerMethodField()
    zone_name = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            if getattr(request.user, "is_superuser", False):
                return
            self.fields["hall"].queryset = self.fields["hall"].queryset.none()
            self.fields["zone"].queryset = self.fields["zone"].queryset.none()
            return

        self.fields["hall"].queryset = self.fields["hall"].queryset.filter(
            zone_or_cabin__restaurant=restaurant,
        )
        self.fields["zone"].queryset = self.fields["zone"].queryset.filter(
            restaurant=restaurant,
        )

    class Meta:
        model = DiningTable
        fields = (
            "id",
            "restaurant_name",
            "hall",
            "zone",
            "zone_name",
            "name",
            "table_number",
            "seat_count",
            "shape",
            "shape_variant",
            "status",
            "position_x",
            "position_y",
            "width",
            "height",
            "rotation",
            "service_fee_enabled",
            "service_fee_percent",
            "is_active",
            "active_session",
            "active_sessions",
            "active_session_count",
            "occupied_guest_count",
            "available_seat_count",
        )

    def _active_sessions(self, obj):
        cached_sessions = getattr(
            obj,
            _SERIALIZER_ACTIVE_SESSIONS_CACHE_ATTR,
            _MISSING,
        )
        if cached_sessions is not _MISSING:
            return cached_sessions

        optimized_sessions = getattr(obj, PREFETCHED_ACTIVE_SESSIONS_ATTR, _MISSING)
        if optimized_sessions is not _MISSING:
            active_sessions = list(optimized_sessions)
            setattr(obj, _SERIALIZER_ACTIVE_SESSIONS_CACHE_ATTR, active_sessions)
            return active_sessions

        prefetched_sessions = getattr(obj, "_prefetched_objects_cache", {}).get(
            "table_sessions"
        )
        if prefetched_sessions is None:
            active_sessions = list(
                obj.table_sessions.filter(status__in=ACTIVE_SESSION_STATUSES).order_by(
                    "-created_at"
                )
            )
        else:
            active_sessions = sorted(
                [
                    session
                    for session in prefetched_sessions
                    if session.status in ACTIVE_SESSION_STATUSES
                ],
                key=lambda item: item.created_at,
                reverse=True,
            )
        setattr(obj, _SERIALIZER_ACTIVE_SESSIONS_CACHE_ATTR, active_sessions)
        return active_sessions

    def _occupied_guest_count(self, obj):
        cached_count = getattr(
            obj,
            _SERIALIZER_OCCUPIED_GUEST_COUNT_CACHE_ATTR,
            _MISSING,
        )
        if cached_count is not _MISSING:
            return cached_count

        occupied_count = sum(
            int(session.guest_count or 0) for session in self._active_sessions(obj)
        )
        setattr(
            obj,
            _SERIALIZER_OCCUPIED_GUEST_COUNT_CACHE_ATTR,
            occupied_count,
        )
        return occupied_count

    def get_active_session(self, obj):
        session = next(iter(self._active_sessions(obj)), None)
        if session is None:
            return None
        return ActiveSessionSummarySerializer(session).data

    def get_active_sessions(self, obj):
        return ActiveSessionSummarySerializer(
            self._active_sessions(obj), many=True
        ).data

    def get_active_session_count(self, obj):
        return len(self._active_sessions(obj))

    def get_occupied_guest_count(self, obj):
        return self._occupied_guest_count(obj)

    def get_available_seat_count(self, obj):
        return max(int(obj.seat_count or 0) - self._occupied_guest_count(obj), 0)

    def get_zone_name(self, obj):
        return getattr(getattr(obj, "zone", None), "name", None)

    def validate_seat_count(self, value):
        if value not in DiningTable.get_supported_seat_counts():
            raise serializers.ValidationError(
                _("Only 2, 3, 4, 5, or 6 seat tables are supported.")
            )
        return value

    def validate_service_fee_percent(self, value):
        if value < Decimal("0") or value > Decimal("99"):
            raise serializers.ValidationError(
                _("Service fee percent must be between 0 and 99.")
            )
        return value

    def validate(self, attrs):
        hall = attrs.get("hall", getattr(self.instance, "hall", None))
        zone = attrs.get("zone")

        request = self.context.get("request")
        if request is not None:
            restaurant = get_request_restaurant(request)
            if hall is not None and hall.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {"hall": _("Selected hall does not belong to this restaurant.")}
                )
            if zone is not None and zone.restaurant_id != restaurant.id:
                raise serializers.ValidationError(
                    {"zone": _("Selected zone does not belong to this restaurant.")}
                )

        if self.instance is not None:
            hall_changed = (
                "hall" in attrs
                and getattr(attrs["hall"], "pk", None) != self.instance.hall_id
            )
            zone_changed = (
                "zone" in attrs
                and getattr(attrs["zone"], "pk", None) != self.instance.zone_id
            )
            if (
                hall_changed or zone_changed
            ) and self.instance.table_sessions.filter(
                status__in=ACTIVE_SESSION_STATUSES
            ).exists():
                error = _(
                    "Close or move active table sessions before changing the table location."
                )
                raise serializers.ValidationError(
                    {
                        field_name: error
                        for field_name, changed in (
                            ("hall", hall_changed),
                            ("zone", zone_changed),
                        )
                        if changed
                    }
                )

        if hall is not None:
            attrs["zone"] = hall.zone_or_cabin

        seat_count = attrs.get("seat_count", getattr(self.instance, "seat_count", 4))
        shape_variant = attrs.get(
            "shape_variant",
            getattr(
                self.instance,
                "shape_variant",
                DiningTable.get_default_shape_variant(seat_count),
            ),
        )

        if shape_variant not in DiningTable.get_supported_variants_for_seat_count(
            seat_count
        ):
            raise serializers.ValidationError(
                {
                    "shape_variant": _(
                        "Shape variant does not match the selected seat count."
                    )
                }
            )

        attrs["shape_variant"] = shape_variant
        if "shape" not in attrs:
            attrs["shape"] = DiningTable.infer_shape_from_variant(shape_variant)
        return attrs
