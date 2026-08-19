from rest_framework import permissions

from apps.devices.models import SecurityEvent
from apps.devices.security import record_security_event
from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES


class NonRestaurantAccountPermission(permissions.BasePermission):
    message = "A restaurant-bound account cannot access this platform endpoint."

    def has_permission(self, request, view):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        restaurant = user.get_restaurant_scope()
        if restaurant is None:
            return True
        record_security_event(
            event_type="TENANT_PLATFORM_SCOPE_DENIED",
            severity=SecurityEvent.Severity.MEDIUM,
            request=request,
            restaurant=restaurant,
            actor=user,
            result="denied",
            metadata={"method": request.method, "path": request.path},
        )
        return False


class PlatformAccountPermission(NonRestaurantAccountPermission):
    """Keep platform-wide mutations unreachable from tenant-bound accounts."""

    message = "A platform account is required for this action."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        return bool(
            getattr(user, "is_superuser", False)
            or user.get_business_partner_scope() is None
        )


class NonRestaurantPermissionRequiredMixin:
    permission_classes = [
        *ADMIN_PERMISSION_CLASSES,
        NonRestaurantAccountPermission,
    ]


class PlatformPermissionRequiredMixin:
    permission_classes = [*ADMIN_PERMISSION_CLASSES, PlatformAccountPermission]
