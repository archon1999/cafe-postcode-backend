from rest_framework import permissions

from apps.accounts.models import User


class IsOwnerDashboardUser(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return (
            user.ui_mode == User.UiMode.ADMIN
            and bool(user.role_id)
            and user.role.code == 'owner'
        )

