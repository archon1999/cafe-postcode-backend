from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import EmployeeProfile, Permission, Role, User
from common.api.query_params import (
    apply_ordering,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from .scopes import filter_queryset_by_optional_restaurant

ROLE_TYPE_VALUES = {'system', 'custom'}
USER_ORDERING_FIELDS = {
    'username': 'username',
    'fullName': 'full_name',
    'phone': 'phone',
    'isActive': 'is_active',
    'role': ('role__name', 'username'),
}
ROLE_ORDERING_FIELDS = {
    'name': 'name',
    'isSystem': 'is_system',
}
PERMISSION_ORDERING_FIELDS = {
    'label': 'name',
    'code': 'code',
    'scope': 'code',
    'action': 'code',
    'description': 'description',
}
POS_PERMISSION_PREFIXES = (
    'hall.',
    'table.',
    'orders.',
    'payments.',
    'cashshift.',
    'payment.',
    'receipt.',
    'kitchen.',
    'stoplist.',
    'cashdesk.',
)


def get_permission_scope(code: str) -> str:
    if code.startswith('dashboard.'):
        return 'dashboard'
    if any(code.startswith(prefix) for prefix in POS_PERMISSION_PREFIXES):
        return 'pos'
    return 'admin'


def admin_user_queryset(request) -> QuerySet[User]:
    queryset = User.objects.select_related(
        'role',
        'restaurant',
        'restaurant_profile__restaurant',
        'restaurant_profile__primary_hall',
        'business_partner_user_profile__business_partner',
        'employee_profile',
        'employee_compensation_profile',
    ).prefetch_related('restaurant_profile__allowed_halls')
    return filter_queryset_by_optional_restaurant(queryset, request, lookup='restaurant_profile__restaurant')


@dataclass(frozen=True)
class UserListFilters:
    search: str = ''
    role_ids: tuple[str, ...] = ()
    employment_statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'UserListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            role_ids=tuple(get_str_list_query_param(query_params, 'role_id_in')),
            employment_statuses=tuple(
                get_str_list_query_param(
                    query_params,
                    'employment_status_in',
                    allowed_values=set(EmployeeProfile.EmploymentStatus.values),
                ),
            ),
            ordering=get_ordering_query_param(query_params, USER_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[User]) -> QuerySet[User]:
        if self.employment_statuses:
            queryset = queryset.filter(employee_profile__employment_status__in=self.employment_statuses)
        else:
            queryset = queryset.exclude(employee_profile__employment_status='archived')
        if self.search:
            queryset = queryset.filter(
                Q(username__icontains=self.search)
                | Q(full_name__icontains=self.search)
                | Q(phone__icontains=self.search)
            )
        if self.role_ids:
            queryset = queryset.filter(role_id__in=self.role_ids)
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
                Q(name__icontains=self.search)
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
    scopes: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'PermissionListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            scopes=tuple(get_str_list_query_param(query_params, 'scope_in')),
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
        if self.scopes:
            allowed_codes = [
                permission.code for permission in queryset.only('code')
                if get_permission_scope(permission.code) in self.scopes
            ]
            queryset = queryset.filter(code__in=allowed_codes)
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
