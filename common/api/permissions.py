from django.contrib.auth import get_user_model

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from apps.users.models import PermissionEndpoint

User = get_user_model()

POS_HALLS_VIEW_PERMISSION = 'pos_halls.view'
POS_TABLES_MANAGE_PERMISSION = 'pos_tables.manage'
POS_TABLE_MENU_VIEW_PERMISSION = 'pos_table_menu.view'
POS_TAKEAWAY_MENU_VIEW_PERMISSION = 'pos_takeaway_menu.view'
POS_KITCHEN_ORDERS_VIEW_PERMISSION = 'pos_kitchen_orders.view'
POS_KITCHEN_ORDERS_VIEW_ALL_PERMISSION = 'pos_kitchen_orders.view_all'
POS_KITCHEN_ORDERS_UPDATE_PERMISSION = 'pos_kitchen_orders.update'
POS_KITCHEN_ORDERS_CANCEL_PERMISSION = 'pos_kitchen_orders.cancel'
POS_OPEN_CHECKS_VIEW_PERMISSION = 'pos_open_checks.view'
POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION = 'pos_payment_order_items.create'
POS_PAYMENT_ORDER_ITEMS_DELETE_PERMISSION = 'pos_payment_order_items.delete'
POS_PAYMENTS_CREATE_PERMISSION = 'pos_payments.create'
POS_CASH_SHIFT_MANAGE_PERMISSION = 'pos_cash_shift.manage'
POS_FISCAL_RECEIPTS_SKIP_PERMISSION = 'pos_fiscal_receipts.skip'
POS_FISCAL_SHIFT_MANAGE_PERMISSION = 'pos_fiscal_shift.manage'
POS_TABLE_RESERVATIONS_MANAGE_PERMISSION = 'pos_table_reservations.manage'


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


def has_permission_code(user, code: str) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    return code in getattr(user, 'permission_codes', [])


def has_any_permission_code(user, *codes: str) -> bool:
    return any(has_permission_code(user, code) for code in codes)


def require_any_permission_code(user, *codes: str, message: str | None = None) -> None:
    if has_any_permission_code(user, *codes):
        return

    raise PermissionDenied(message or EndpointRBACPermission.message)


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
