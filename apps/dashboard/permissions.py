from rest_framework import permissions


class IsOwnerDashboardUser(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return 'dashboard.view' in set(user.get_effective_permission_codes())
