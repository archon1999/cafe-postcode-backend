from rest_framework import permissions

from common.api.permissions import HasPermissionCode

ADMIN_PERMISSION_CLASSES = [permissions.IsAuthenticated, HasPermissionCode]


class AdminAllowAnyMixin:
    permission_classes = [permissions.AllowAny]


class AdminAuthenticatedMixin:
    permission_classes = [permissions.IsAuthenticated]


class AdminPermissionRequiredMixin:
    permission_classes = ADMIN_PERMISSION_CLASSES
