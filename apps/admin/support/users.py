from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import EmployeeProfile, Permission, Role, User
from common.api.scopes import get_optional_request_restaurant
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
    'scope': 'surface',
    'action': 'action',
    'description': 'description',
}

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
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None and getattr(request.user, 'is_authenticated', False):
        restaurant = request.user.get_restaurant_scope()
    if restaurant is None:
        return queryset
    return queryset.filter(Q(restaurant_profile__restaurant=restaurant) | Q(restaurant=restaurant)).distinct()


def scoped_role_queryset(request) -> QuerySet[Role]:
    queryset = Role.objects.prefetch_related('permissions__endpoints').all()
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None and getattr(request.user, 'is_authenticated', False):
        restaurant = request.user.get_restaurant_scope()
    if restaurant is None:
        return queryset

    entitlement = getattr(restaurant, 'entitlement', None)
    if entitlement is None:
        return queryset.none()

    allowed_role_ids = set(entitlement.allowed_roles.values_list('id', flat=True))
    if entitlement.tariff_id:
        allowed_role_ids.update(entitlement.tariff.allowed_roles.values_list('id', flat=True))

    if not allowed_role_ids:
        return queryset.none()

    return queryset.filter(id__in=allowed_role_ids, is_system=True)


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
            queryset = queryset.filter(surface__in=self.scopes)
        if self.actions:
            queryset = queryset.filter(action__in=self.actions)
        return apply_ordering(queryset, self.ordering, default_ordering=('code',))


class AdminUserQuerysetMixin:
    def get_user_queryset(self) -> QuerySet[User]:
        return admin_user_queryset(self.request)

    def get_filtered_user_queryset(self) -> QuerySet[User]:
        return UserListFilters.from_request(self.request).apply(self.get_user_queryset())


def prevent_system_role_delete(instance: Role):
    if instance.is_system:
        raise serializers.ValidationError({'detail': _('System roles cannot be deleted.')})
