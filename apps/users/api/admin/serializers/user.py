from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import Hall
from apps.users.helpers import (
    get_employee_profile_model,
    get_role_model,
    get_user_model,
)
from apps.users.selectors.users import employee_role_queryset
from common.api.scopes import get_optional_request_restaurant

from .role import RoleSerializer
from .user_persistence import UserPersistenceMixin
from .user_validation import UserValidationMixin

EmployeeProfile = get_employee_profile_model()
Role = get_role_model()
User = get_user_model()


class UserSerializer(
    UserValidationMixin, UserPersistenceMixin, serializers.ModelSerializer
):
    user_surface = "system"
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        source="role", queryset=Role.objects.all(), write_only=True
    )
    permission_codes = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )
    restaurant_id = serializers.SerializerMethodField()
    restaurant_name = serializers.SerializerMethodField()
    business_partner_id = serializers.SerializerMethodField()
    primary_hall_id = serializers.PrimaryKeyRelatedField(
        source="restaurant_profile.primary_hall",
        queryset=Hall.objects.all(),
        required=False,
        allow_null=True,
    )
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(
        source="restaurant_profile.allowed_halls",
        queryset=Hall.objects.all(),
        many=True,
        required=False,
    )
    hall_switch_permission = serializers.BooleanField(
        source="restaurant_profile.hall_switch_permission", required=False
    )
    passport_series = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )
    pnfl = serializers.CharField(required=False, allow_blank=True, write_only=True)
    birth_date = serializers.DateField(required=False, allow_null=True, write_only=True)
    employment_status = serializers.ChoiceField(
        choices=EmployeeProfile.EmploymentStatus.choices,
        required=False,
        write_only=True,
    )
    salary_type = serializers.ChoiceField(
        choices=EmployeeProfile.SalaryType.choices,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    base_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        write_only=True,
    )
    kpi_percent = serializers.IntegerField(
        required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "full_name",
            "phone",
            "is_active",
            "role",
            "role_id",
            "restaurant_id",
            "restaurant_name",
            "business_partner_id",
            "hall_switch_permission",
            "primary_hall_id",
            "allowed_hall_ids",
            "passport_series",
            "pnfl",
            "birth_date",
            "employment_status",
            "salary_type",
            "base_amount",
            "kpi_percent",
            "permission_codes",
        )
        read_only_fields = ("restaurant_id", "restaurant_name", "business_partner_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user_surface == "employee":
            self.fields["username"].required = False
            self.fields["username"].allow_blank = True
            request = self.context.get("request")
            if request is not None:
                self.fields["role_id"].queryset = employee_role_queryset(request)
                restaurant = get_optional_request_restaurant(request)
                if restaurant is not None:
                    hall_queryset = Hall.objects.filter(
                        zone_or_cabin__restaurant=restaurant
                    )
                elif getattr(request.user, "is_superuser", False):
                    hall_queryset = Hall.objects.all()
                else:
                    hall_queryset = Hall.objects.none()
                self.fields["primary_hall_id"].queryset = hall_queryset
                allowed_halls_field = self.fields["allowed_hall_ids"]
                if hasattr(allowed_halls_field, "child_relation"):
                    allowed_halls_field.child_relation.queryset = hall_queryset
                else:
                    allowed_halls_field.queryset = hall_queryset

    def get_restaurant_id(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, "id", None)

    def get_restaurant_name(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, "name", None)

    def get_business_partner_id(self, instance):
        business_partner = instance.get_business_partner_scope()
        return getattr(business_partner, "id", None)

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            detail = dict(exc.detail)
            generic_relation_errors = {
                "role_id": ("roleId", _("Invalid role.")),
                "primary_hall_id": ("primaryHallId", _("Invalid primary hall.")),
                "allowed_hall_ids": ("allowedHallIds", _("Invalid allowed halls.")),
            }
            changed = False
            for source_name, (target_name, message) in generic_relation_errors.items():
                if source_name not in detail:
                    continue
                detail.pop(source_name)
                detail[target_name] = [message]
                changed = True
            if not changed:
                raise
            raise serializers.ValidationError(detail) from None


class EmployeeSerializer(UserSerializer):
    user_surface = "employee"
