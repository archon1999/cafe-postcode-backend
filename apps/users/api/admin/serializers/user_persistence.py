from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.users.helpers import (
    get_employee_profile_model,
    get_restaurant_profile_model,
    get_user_model,
)
from apps.users.selectors.users import role_requires_login_credentials

from .user_validation import get_optional_restaurant_profile

EmployeeProfile = get_employee_profile_model()
RestaurantProfile = get_restaurant_profile_model()
User = get_user_model()


class UserPersistenceMixin:
    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, "employee_profile", None)
        restaurant_profile = get_optional_restaurant_profile(instance)
        data["passport_series"] = profile.passport_series if profile else ""
        data["pnfl"] = profile.pnfl if profile else ""
        data["birth_date"] = (
            profile.birth_date.isoformat() if profile and profile.birth_date else None
        )
        data["employment_status"] = (
            profile.employment_status
            if profile
            else EmployeeProfile.EmploymentStatus.ACTIVE
        )
        data["salary_type"] = (
            profile.salary_type if profile and profile.salary_type else None
        )
        data["base_amount"] = (
            float(profile.base_amount)
            if profile and profile.base_amount is not None
            else None
        )
        data["kpi_percent"] = profile.kpi_percent if profile else None
        data["primary_hall_id"] = getattr(restaurant_profile, "primary_hall_id", None)
        data["allowed_hall_ids"] = (
            list(restaurant_profile.allowed_halls.values_list("id", flat=True))
            if restaurant_profile
            else []
        )
        data["hall_switch_permission"] = bool(
            getattr(restaurant_profile, "hall_switch_permission", False)
        )
        return data

    @staticmethod
    def _extract_profile_data(validated_data):
        return {
            key: validated_data.pop(key)
            for key in ("passport_series", "pnfl", "birth_date", "employment_status")
            if key in validated_data
        }

    @staticmethod
    def _normalize_profile_status(
        validated_data,
        profile_data,
        current_status=EmployeeProfile.EmploymentStatus.ACTIVE,
    ):
        if "employment_status" not in profile_data:
            profile_data["employment_status"] = current_status
        if (
            profile_data["employment_status"]
            == EmployeeProfile.EmploymentStatus.ARCHIVED
        ):
            validated_data["is_active"] = False
            return
        if "is_active" in validated_data:
            profile_data["employment_status"] = (
                EmployeeProfile.EmploymentStatus.ACTIVE
                if validated_data["is_active"]
                else EmployeeProfile.EmploymentStatus.INACTIVE
            )
            return
        validated_data["is_active"] = (
            profile_data["employment_status"] == EmployeeProfile.EmploymentStatus.ACTIVE
        )

    @staticmethod
    def _validate_compensation_data(profile_data):
        salary_type = profile_data.get("salary_type") or ""
        base_amount = profile_data.get("base_amount")
        kpi_percent = profile_data.get("kpi_percent")
        if salary_type and base_amount is None:
            raise serializers.ValidationError(
                {
                    "baseAmount": _(
                        "Base amount is required for the selected salary type."
                    )
                }
            )
        if base_amount is not None and base_amount < 0:
            raise serializers.ValidationError(
                {"baseAmount": _("Base amount must be greater than or equal to 0.")}
            )
        if kpi_percent is not None and kpi_percent < 0:
            raise serializers.ValidationError(
                {"kpiPercent": _("KPI percent must be greater than or equal to 0.")}
            )

    @staticmethod
    def _save_profile(instance, profile_data):
        profile, _ = EmployeeProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()

    def _save_restaurant_profile(
        self, instance, restaurant_profile_data, pin, *, clear_pin=False
    ):
        restaurant = (
            restaurant_profile_data.pop("restaurant", None)
            or instance.get_restaurant_scope()
        )
        if restaurant is None:
            return None
        restaurant_profile, _ = RestaurantProfile.objects.get_or_create(
            user=instance,
            defaults={"restaurant": restaurant},
        )
        if restaurant_profile.restaurant_id != restaurant.id:
            restaurant_profile.restaurant = restaurant
        if "hall_switch_permission" in restaurant_profile_data:
            restaurant_profile.hall_switch_permission = restaurant_profile_data[
                "hall_switch_permission"
            ]
        if "primary_hall" in restaurant_profile_data:
            restaurant_profile.primary_hall = restaurant_profile_data["primary_hall"]
        restaurant_profile.save()
        allowed_halls = restaurant_profile_data.get("allowed_halls")
        if allowed_halls is not None:
            restaurant_profile.allowed_halls.set(allowed_halls)
        if clear_pin:
            instance.pin_code = ""
            instance.save(update_fields=["pin_code"])
            restaurant_profile.pin_code = ""
            restaurant_profile.save(update_fields=["pin_code"])
        elif pin:
            instance.set_pin(pin)
        return restaurant_profile

    def create(self, validated_data):
        restaurant_profile_data = validated_data.pop("restaurant_profile", {})
        restaurant = validated_data.pop("restaurant", None)
        role = validated_data.get("role")
        requires_login_credentials = (
            self.user_surface == "employee" and role_requires_login_credentials(role)
        )
        profile_data = self._extract_profile_data(validated_data)
        profile_data.update(
            {
                key: validated_data.pop(key)
                for key in ("salary_type", "base_amount", "kpi_percent")
                if key in validated_data
            }
        )
        self._normalize_profile_status(validated_data, profile_data)
        self._validate_compensation_data(profile_data)
        request = self.context.get("request")
        password = request.data.get("password") if request else None
        pin = request.data.get("pin") if request else None
        restaurant = restaurant or (
            self._get_target_restaurant() if self.user_surface == "employee" else None
        )
        if restaurant is not None:
            restaurant_profile_data["restaurant"] = restaurant
        if self.user_surface == "employee" and not requires_login_credentials:
            validated_data["username"] = self._generate_internal_username(
                validated_data.get("full_name", ""), restaurant=restaurant
            )
        user = User.objects.create(**validated_data)
        if self.user_surface == "employee":
            if requires_login_credentials:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save(update_fields=["password"])
        elif password:
            user.set_password(password)
            user.save(update_fields=["password"])
        self._save_restaurant_profile(
            user,
            restaurant_profile_data,
            pin if not requires_login_credentials else None,
            clear_pin=requires_login_credentials,
        )
        self._save_profile(user, profile_data)
        user.refresh_from_db()
        return user

    def update(self, instance, validated_data):
        restaurant_profile_data = validated_data.pop("restaurant_profile", {})
        restaurant = validated_data.pop("restaurant", None)
        role = validated_data.get("role", instance.role)
        requires_login_credentials = (
            self.user_surface == "employee" and role_requires_login_credentials(role)
        )
        if restaurant is not None:
            restaurant_profile_data["restaurant"] = restaurant
        profile_data = self._extract_profile_data(validated_data)
        profile_data.update(
            {
                key: validated_data.pop(key)
                for key in ("salary_type", "base_amount", "kpi_percent")
                if key in validated_data
            }
        )
        current_status = getattr(
            getattr(instance, "employee_profile", None),
            "employment_status",
            EmployeeProfile.EmploymentStatus.ACTIVE,
        )
        self._normalize_profile_status(
            validated_data, profile_data, current_status=current_status
        )
        self._validate_compensation_data(profile_data)
        if self.user_surface == "employee" and not requires_login_credentials:
            validated_data.pop("username", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        request = self.context.get("request")
        password = request.data.get("password") if request else None
        pin = request.data.get("pin") if request else None
        if self.user_surface == "employee":
            if requires_login_credentials and password:
                instance.set_password(password)
            elif not requires_login_credentials:
                instance.set_unusable_password()
        elif password:
            instance.set_password(password)
        instance.save()
        self._save_restaurant_profile(
            instance,
            restaurant_profile_data,
            pin if not requires_login_credentials else None,
            clear_pin=requires_login_credentials,
        )
        self._save_profile(instance, profile_data)
        instance.refresh_from_db()
        return instance
