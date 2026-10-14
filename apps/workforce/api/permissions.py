from rest_framework import permissions

from apps.users.models import AuthSession
from apps.workforce.models import GeofenceConfig


def manager_has_code(user, code: str) -> bool:
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    return bool(user.is_superuser or code in user.permission_codes)


class StaffSessionRequired(permissions.BasePermission):
    message = 'An active staff session for this restaurant is required.'

    def has_permission(self, request, view):
        session = request.auth
        user = request.user
        if not isinstance(session, AuthSession) or session.surface != 'staff':
            return False
        if not user or not user.is_authenticated or not user.restaurant_access_active:
            return False
        restaurant = user.get_restaurant_scope()
        if not restaurant or session.restaurant_id != restaurant.id:
            return False
        if getattr(view, 'allow_disabled_workforce', False):
            return True
        return GeofenceConfig.objects.filter(restaurant=restaurant, workforce_enabled=True).exists()


class ManagerCodeRequired(StaffSessionRequired):
    message = 'Manager workforce permission is required.'

    def has_permission(self, request, view):
        code = getattr(view, 'method_codes', {}).get(request.method, view.required_code)
        return super().has_permission(request, view) and manager_has_code(request.user, code)
