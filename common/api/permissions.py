from django.contrib.auth import get_user_model

from rest_framework import permissions

from apps.accounts.models import PermissionEndpoint

User = get_user_model()


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        obj_user = None
        if isinstance(obj, User):
            obj_user = obj
        elif hasattr(obj, 'user'):
            obj_user = obj.user
        elif hasattr(obj, 'author'):
            obj_user = obj.author

        return obj_user == request.user


class IsOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        obj_user = None
        if isinstance(obj, User):
            obj_user = obj
        elif hasattr(obj, 'user'):
            obj_user = obj.user
        elif hasattr(obj, 'author'):
            obj_user = obj.author

        return obj_user == request.user

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        return super().has_permission(request, view)


class OnlySelfOrAdminRead(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        obj_user = None
        if isinstance(obj, User):
            obj_user = obj
        elif hasattr(obj, 'user'):
            obj_user = obj.user
        elif hasattr(obj, 'author'):
            obj_user = obj.author

        if request.method in permissions.SAFE_METHODS:
            return obj_user == request.user or request.user.is_superuser

        return False


class IsOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        obj_user = None
        if isinstance(obj, User):
            obj_user = obj
        elif hasattr(obj, 'user'):
            obj_user = obj.user
        elif hasattr(obj, 'author'):
            obj_user = obj.author

        return obj_user == request.user or request.user.is_superuser


class ReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.method in permissions.SAFE_METHODS


class IsAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser

    def has_permission(self, request, view):
        return request.user.is_superuser


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser or \
               request.method in permissions.SAFE_METHODS

    def has_permission(self, request, view):
        return request.user.is_superuser or \
               request.method in permissions.SAFE_METHODS


AUTHENTICATED_RBAC_EXEMPT_ENDPOINTS = {
    ('GET', 'api/v1/pos/auth/me/'),
    ('POST', 'api/v1/pos/auth/logout/'),
    ('GET', 'api/v1/admin/auth/me/'),
    ('POST', 'api/v1/admin/auth/logout/'),
    ('POST', 'api/v1/dashboard/auth/logout/'),
}


class EndpointRBACPermission(permissions.BasePermission):
    message = 'You do not have permission to perform this action.'

    @staticmethod
    def _allows_any(view) -> bool:
        return any(
            isinstance(permission_class, type) and issubclass(permission_class, permissions.AllowAny)
            for permission_class in getattr(view, 'permission_classes', [])
        )

    @staticmethod
    def _get_route(request) -> str:
        resolver_match = getattr(request, 'resolver_match', None)
        return getattr(resolver_match, 'route', '') or ''

    @staticmethod
    def _normalize_method(method: str) -> str:
        normalized_method = method.upper()
        if normalized_method == 'HEAD':
            return 'GET'
        return normalized_method

    def has_permission(self, request, view):
        if request.method.upper() == 'OPTIONS':
            return True

        if self._allows_any(view):
            return True

        if not request.user or not request.user.is_authenticated:
            return False

        route = self._get_route(request)
        method = self._normalize_method(request.method)

        if (method, route) in AUTHENTICATED_RBAC_EXEMPT_ENDPOINTS:
            return True

        if request.user.is_superuser:
            return True

        if not route:
            return False

        permission_codes = request.user.permission_codes
        if not permission_codes:
            return False

        return PermissionEndpoint.objects.filter(
            url=route,
            method=method,
            permission__code__in=permission_codes,
        ).exists()


class HasPermissionCode(EndpointRBACPermission):
    """Backward-compatible alias while views are migrated to endpoint RBAC."""
