from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import Permission, Role, User
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from .scopes import filter_queryset_by_optional_restaurant

USER_UI_MODE_VALUES = {choice for choice, _label in User.UiMode.choices}
ROLE_TYPE_VALUES = {'system', 'custom'}
USER_ORDERING_FIELDS = {
    'username': 'username',
    'fullName': 'full_name',
    'phone': 'phone',
    'uiMode': 'ui_mode',
    'isActive': 'is_active',
    'role': ('role__name', 'username'),
}
ROLE_ORDERING_FIELDS = {
    'name': 'name',
    'code': 'code',
    'isSystem': 'is_system',
}
PERMISSION_ORDERING_FIELDS = {
    'label': 'code',
    'code': 'code',
    'category': 'code',
    'action': 'code',
    'description': 'description',
}


def admin_user_queryset(request) -> QuerySet[User]:
    queryset = User.objects.select_related(
        'role',
        'branch',
        'restaurant',
        'primary_hall',
        'employee_profile',
        'employee_compensation_profile',
    ).prefetch_related('allowed_halls')
    return filter_queryset_by_optional_restaurant(queryset, request)


@dataclass(frozen=True)
class UserListFilters:
    search: str = ''
    role_codes: tuple[str, ...] = ()
    ui_modes: tuple[str, ...] = ()
    is_active: bool | None = None
    include_archived: bool = False
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'UserListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            role_codes=tuple(get_str_list_query_param(query_params, 'role_code_in')),
            ui_modes=tuple(get_str_list_query_param(query_params, 'ui_mode_in', allowed_values=USER_UI_MODE_VALUES)),
            is_active=get_bool_query_param(query_params, 'is_active'),
            include_archived=bool(get_bool_query_param(query_params, 'include_archived') or False),
            ordering=get_ordering_query_param(query_params, USER_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[User]) -> QuerySet[User]:
        if not self.include_archived:
            queryset = queryset.exclude(employee_profile__employment_status='archived')
        if self.search:
            queryset = queryset.filter(
                Q(username__icontains=self.search)
                | Q(full_name__icontains=self.search)
                | Q(phone__icontains=self.search)
            )
        if self.role_codes:
            queryset = queryset.filter(role__code__in=self.role_codes)
        if self.ui_modes:
            queryset = queryset.filter(ui_mode__in=self.ui_modes)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset, self.ordering, default_ordering=('username',))


@dataclass(frozen=True)
class RoleListFilters:
    search: str = ''
    types: tuple[str, ...] = ()
    permission_codes: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'RoleListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            types=tuple(get_str_list_query_param(query_params, 'type_in', allowed_values=ROLE_TYPE_VALUES)),
            permission_codes=tuple(get_str_list_query_param(query_params, 'permission_code_in')),
            ordering=get_ordering_query_param(query_params, ROLE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Role]) -> QuerySet[Role]:
        if self.search:
            queryset = queryset.filter(
                Q(code__icontains=self.search)
                | Q(name__icontains=self.search)
                | Q(description__icontains=self.search)
                | Q(permissions__code__icontains=self.search)
            )
        if self.types and len(self.types) == 1:
            queryset = queryset.filter(is_system=self.types[0] == 'system')
        if self.permission_codes:
            queryset = queryset.filter(permissions__code__in=self.permission_codes)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('name',))


@dataclass(frozen=True)
class PermissionListFilters:
    search: str = ''
    categories: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'PermissionListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            categories=tuple(get_str_list_query_param(query_params, 'category_in')),
            actions=tuple(get_str_list_query_param(query_params, 'action_in')),
            ordering=get_ordering_query_param(query_params, PERMISSION_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Permission]) -> QuerySet[Permission]:
        if self.search:
            queryset = queryset.filter(
                Q(code__icontains=self.search)
                | Q(name__icontains=self.search)
                | Q(description__icontains=self.search)
            )
        if self.categories:
            category_query = Q()
            for category in self.categories:
                category_query |= Q(code__istartswith=f'{category}.')
            queryset = queryset.filter(category_query)
        if self.actions:
            action_query = Q()
            for action in self.actions:
                action_query |= Q(code__iendswith=f'.{action}')
            queryset = queryset.filter(action_query)
        return apply_ordering(queryset, self.ordering, default_ordering=('code',))


class AdminUserQuerysetMixin:
    def get_user_queryset(self) -> QuerySet[User]:
        return admin_user_queryset(self.request)

    def get_filtered_user_queryset(self) -> QuerySet[User]:
        return UserListFilters.from_request(self.request).apply(self.get_user_queryset())


def prevent_system_role_delete(instance: Role):
    if instance.is_system:
        raise serializers.ValidationError({'detail': _('System roles cannot be deleted.')})
