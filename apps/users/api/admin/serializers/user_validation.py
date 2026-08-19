from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import (
    ObjectDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.users.helpers import get_user_model
from apps.users.permission_registry import RESTAURANT_ADMIN_UI_ROLES
from apps.users.selectors.users import (
    role_is_allowed_for_employee_surface,
    role_requires_login_credentials,
)
from common.api.scopes import get_optional_request_restaurant

User = get_user_model()


def get_optional_restaurant_profile(instance):
    if instance is None:
        return None
    try:
        return instance.restaurant_profile
    except ObjectDoesNotExist:
        return None


class UserValidationMixin:
    def _get_target_restaurant(self):
        request = self.context.get("request")
        request_restaurant = (
            get_optional_request_restaurant(request) if request is not None else None
        )
        if request_restaurant is not None:
            return request_restaurant
        if self.instance is not None:
            restaurant = self.instance.get_restaurant_scope()
            if restaurant is not None:
                return restaurant
        if request is not None and getattr(request.user, "is_authenticated", False):
            return request.user.get_restaurant_scope()
        return None

    def _generate_internal_username(
        self, full_name: str, restaurant=None, instance=None
    ) -> str:
        person_slug = slugify(full_name) or "employee"
        restaurant_slug = slugify(getattr(restaurant, "name", "")) or "restaurant"
        base_username = f"{restaurant_slug}-{person_slug}"
        username = base_username[:150]
        suffix = 2
        queryset = User.objects.all()
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)
        while queryset.filter(username=username).exists():
            suffix_text = f"-{suffix}"
            username = f"{base_username[: max(1, 150 - len(suffix_text))]}{suffix_text}"
            suffix += 1
        return username

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        request_data = getattr(request, "data", {}) or {}
        actor = getattr(request, "user", None)
        pin = request_data.get("pin")
        password = request_data.get("password")
        restaurant = self._get_target_restaurant()
        role = attrs.get("role", getattr(self.instance, "role", None))
        requires_login_credentials = (
            self.user_surface == "employee" and role_requires_login_credentials(role)
        )
        restaurant_profile_data = attrs.get("restaurant_profile", {}) or {}
        current_restaurant_profile = get_optional_restaurant_profile(self.instance)
        primary_hall = restaurant_profile_data.get(
            "primary_hall",
            getattr(current_restaurant_profile, "primary_hall", None),
        )

        if "allowed_halls" in restaurant_profile_data:
            allowed_halls = list(restaurant_profile_data["allowed_halls"])
        elif current_restaurant_profile is not None:
            allowed_halls = list(current_restaurant_profile.allowed_halls.all())
        else:
            allowed_halls = []

        if self.user_surface == "employee" and restaurant is None:
            raise serializers.ValidationError(
                {"detail": _("Employees must belong to a restaurant scope.")}
            )
        if (
            self.user_surface == "employee"
            and role is not None
            and not role_is_allowed_for_employee_surface(role)
        ):
            raise serializers.ValidationError(
                {"roleId": _("Selected role is not available for employees.")}
            )

        if requires_login_credentials:
            errors = {}
            username = attrs.get("username", getattr(self.instance, "username", ""))
            if isinstance(username, str):
                username = username.strip()
            if not username:
                errors["username"] = _("Username is required for admin employees.")
            else:
                attrs["username"] = username
            if self.instance is None and (
                not isinstance(password, str) or not password.strip()
            ):
                errors["password"] = _("Password is required for admin employees.")
            if pin not in (None, ""):
                errors["pin"] = _("PIN code is not used for admin employees.")
            if errors:
                raise serializers.ValidationError(errors)

        if isinstance(password, str) and password:
            try:
                validate_password(password, user=self.instance)
            except DjangoValidationError as error:
                raise serializers.ValidationError(
                    {"password": list(error.messages)}
                ) from error

        if (
            restaurant is not None
            and primary_hall is not None
            and primary_hall.restaurant_id != restaurant.id
        ):
            raise serializers.ValidationError(
                {
                    "primaryHallId": _(
                        "Selected hall does not belong to the selected restaurant."
                    )
                }
            )
        if restaurant is not None and any(
            hall.restaurant_id != restaurant.id for hall in allowed_halls
        ):
            raise serializers.ValidationError(
                {
                    "allowedHallIds": _(
                        "All allowed halls must belong to the selected restaurant."
                    )
                }
            )

        if (
            restaurant is not None
            and role is not None
            and not getattr(actor, "is_superuser", False)
        ):
            entitlement = getattr(restaurant, "entitlement", None)
            allowed_role_ids = set()
            if entitlement is not None:
                allowed_role_ids.update(
                    entitlement.allowed_roles.values_list("id", flat=True)
                )
                if entitlement.tariff_id:
                    allowed_role_ids.update(
                        entitlement.tariff.allowed_roles.values_list("id", flat=True)
                    )
            if role.id not in allowed_role_ids:
                raise serializers.ValidationError(
                    {"roleId": _("Selected role is not available for this restaurant.")}
                )

            actor_role_code = getattr(actor, "role_code", None)
            actor_is_restaurant_admin = (
                actor_role_code in RESTAURANT_ADMIN_UI_ROLES
            )
            assigns_different_admin_role = (
                actor_is_restaurant_admin
                and role_requires_login_credentials(role)
                and role.code != actor_role_code
            )
            target_permission_codes = set(
                role.permissions.values_list("code", flat=True)
            )
            if entitlement is not None:
                target_permission_codes.intersection_update(
                    entitlement.get_effective_permission_codes()
                )
            actor_permission_codes = set(getattr(actor, "permission_codes", ()))
            exceeds_actor_permissions = (
                not actor_is_restaurant_admin
                and not target_permission_codes.issubset(actor_permission_codes)
            )
            if assigns_different_admin_role or exceeds_actor_permissions:
                raise serializers.ValidationError(
                    {
                        "roleId": _(
                            "You cannot assign a role with permissions you do not have."
                        )
                    }
                )

        if pin in (None, ""):
            return attrs
        if not isinstance(pin, str):
            raise serializers.ValidationError({"pin": _("PIN code must be a string.")})
        if not pin.isdigit():
            raise serializers.ValidationError(
                {"pin": _("PIN code must contain only digits.")}
            )
        if len(pin) != 4:
            raise serializers.ValidationError(
                {"pin": _("PIN code must be exactly 4 digits.")}
            )

        duplicate_users = User.objects.exclude(
            restaurant_profile__pin_code=""
        ).select_related("role", "restaurant_profile")
        if restaurant is not None:
            duplicate_users = duplicate_users.filter(
                restaurant_profile__restaurant=restaurant
            )
        if self.instance:
            duplicate_users = duplicate_users.exclude(pk=self.instance.pk)
        if any(user.check_pin(pin) for user in duplicate_users):
            raise serializers.ValidationError(
                {"pin": _("This PIN code is already assigned to another POS user.")}
            )
        return attrs
