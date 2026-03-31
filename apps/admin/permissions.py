from rest_framework import permissions

from common.api.permissions import EndpointRBACPermission

ADMIN_PERMISSION_CLASSES = [permissions.IsAuthenticated, EndpointRBACPermission]


class AdminAllowAnyMixin:
    permission_classes = [permissions.AllowAny]


class AdminAuthenticatedMixin:
    permission_classes = ADMIN_PERMISSION_CLASSES


class AdminPermissionRequiredMixin:
    permission_classes = ADMIN_PERMISSION_CLASSES
