from django.contrib.auth import get_user_model

from rest_framework import permissions

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


class HasPermissionCode(permissions.BasePermission):
    permission_code = ''

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        if hasattr(view, 'get_permission_code'):
            code = view.get_permission_code()
        else:
            code = getattr(view, 'permission_code', self.permission_code)
        if not code:
            return True

        return request.user.has_permission_code(code)
