from rest_framework import permissions

from apps.devices.models import SecurityEvent
from apps.devices.security import record_security_event
from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES


class NonRestaurantAccountPermission(permissions.BasePermission):
    message = "A restaurant-bound account cannot access this system endpoint."

    def has_permission(self, request, view):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        restaurant = user.get_restaurant_scope()
        if restaurant is None:
            return True
        record_security_event(
            event_type="TENANT_SYSTEM_SCOPE_DENIED",
            severity=SecurityEvent.Severity.MEDIUM,
            request=request,
            restaurant=restaurant,
            actor=user,
            result="denied",
            metadata={"method": request.method, "path": request.path},
        )
        return False


class PlatformAccountPermission(NonRestaurantAccountPermission):
    message = "A platform account is required for this action."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        return bool(
            getattr(user, "is_superuser", False)
            or user.get_business_partner_scope() is None
        )


class RoleCollectionScopePermission(NonRestaurantAccountPermission):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.get_business_partner_scope() is None


class NonRestaurantPermissionRequiredMixin:
    permission_classes = [
        *ADMIN_PERMISSION_CLASSES,
        NonRestaurantAccountPermission,
    ]


class PlatformPermissionRequiredMixin:
    permission_classes = [*ADMIN_PERMISSION_CLASSES, PlatformAccountPermission]


class RoleCollectionPermissionRequiredMixin:
    permission_classes = [*ADMIN_PERMISSION_CLASSES, RoleCollectionScopePermission]
