from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions

from apps.users.models import AuthSession
from common.api.permissions import EndpointRBACPermission

ADMIN_PERMISSION_CLASSES = [permissions.IsAuthenticated, EndpointRBACPermission]


class AdminAllowAnyMixin:
    permission_classes = [permissions.AllowAny]


class AdminAuthenticatedMixin:
    permission_classes = ADMIN_PERMISSION_CLASSES


class AdminPermissionRequiredMixin:
    permission_classes = ADMIN_PERMISSION_CLASSES


class RecentAdminMFAPermission(permissions.BasePermission):
    message = {'code': 'mfa_step_up_required', 'detail': 'Recent MFA verification is required for this action.'}

    def has_permission(self, request, view):
        if not settings.ADMIN_MFA_REQUIRED:
            return True
        if request.user.is_authenticated and not request.user.is_superuser:
            return True
        session = request.auth if isinstance(request.auth, AuthSession) else None
        return bool(
            session
            and session.surface == AuthSession.Surface.ADMIN
            and session.mfa_verified_at
            and session.mfa_verified_at > timezone.now() - timedelta(minutes=15)
        )


class AdminRecentMFARequiredMixin:
    permission_classes = [*ADMIN_PERMISSION_CLASSES, RecentAdminMFAPermission]
