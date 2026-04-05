from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.users.constants import POS_UI_PERMISSION_CODES
from apps.users.helpers import (
    get_employee_profile_model,
    get_permission_model,
    get_role_model,
    get_user_model,
)
from common.api.query_params import (
    apply_ordering,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from common.api.scopes import get_optional_request_restaurant

EmployeeProfile = get_employee_profile_model()
Permission = get_permission_model()
Role = get_role_model()
User = get_user_model()

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


def employee_user_queryset(request) -> QuerySet:
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None and getattr(request.user, 'is_authenticated', False):
        restaurant = request.user.get_restaurant_scope()
    if restaurant is None:
        return User.objects.none()

    return (
        User.objects.select_related(
            'role',
            'restaurant_profile__restaurant',
            'restaurant_profile__primary_hall',
            'business_partner_profile',
            'employee_profile',
        )
        .prefetch_related('restaurant_profile__allowed_halls')
        .filter(restaurant_profile__restaurant=restaurant)
        .filter(Q(password__startswith='!') | Q(restaurant_profile__pin_code__gt=''))
        .exclude(is_superuser=True)
        .distinct()
    )


def system_user_queryset(_request) -> QuerySet:
    return (
        User.objects.select_related(
            'role',
            'restaurant_profile__restaurant',
            'restaurant_profile__primary_hall',
            'business_partner_profile',
            'employee_profile',
        )
        .prefetch_related('restaurant_profile__allowed_halls')
        .exclude(Q(password__startswith='!') | Q(restaurant_profile__pin_code__gt=''))
        .distinct()
    )


def admin_user_queryset(request) -> QuerySet:
    queryset = User.objects.select_related(
        'role',
        'restaurant_profile__restaurant',
        'restaurant_profile__primary_hall',
        'business_partner_profile',
        'employee_profile',
    ).prefetch_related('restaurant_profile__allowed_halls')
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None and getattr(request.user, 'is_authenticated', False):
        restaurant = request.user.get_restaurant_scope()
    if restaurant is None:
        return queryset
    return queryset.filter(restaurant_profile__restaurant=restaurant).distinct()


def scoped_role_queryset(request) -> QuerySet:
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


def employee_role_queryset(request) -> QuerySet:
    return scoped_role_queryset(request).filter(permissions__code__in=POS_UI_PERMISSION_CODES).distinct()


def role_has_pos_permissions(role: Role | None) -> bool:
    if role is None:
        return False
    return role.permissions.filter(code__in=POS_UI_PERMISSION_CODES).exists()


@dataclass(frozen=True)
class UserListFilters:
    search: str = ''
    role_ids: tuple[str, ...] = ()
    employment_statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()
    include_username_in_search: bool = True
    default_ordering: tuple[str, ...] = ('username',)

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

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.employment_statuses:
            queryset = queryset.filter(employee_profile__employment_status__in=self.employment_statuses)
        else:
            queryset = queryset.exclude(employee_profile__employment_status='archived')
        if self.search:
            search_query = Q(full_name__icontains=self.search) | Q(phone__icontains=self.search)
            if self.include_username_in_search:
                search_query |= Q(username__icontains=self.search)
            queryset = queryset.filter(search_query)
        if self.role_ids:
            queryset = queryset.filter(role_id__in=self.role_ids)
        return apply_ordering(queryset, self.ordering, default_ordering=self.default_ordering)


@dataclass(frozen=True)
class RoleListFilters:
    search: str = ''
    types: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'RoleListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            types=tuple(get_str_list_query_param(query_params, 'type_in', allowed_values=ROLE_TYPE_VALUES)),
            ordering=get_ordering_query_param(query_params, ROLE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(description__icontains=self.search)
                | Q(permissions__code__icontains=self.search)
            )
        if self.types and len(self.types) == 1:
            queryset = queryset.filter(is_system=self.types[0] == 'system')
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

    def apply(self, queryset: QuerySet) -> QuerySet:
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
    user_surface = 'system'

    def get_user_queryset(self) -> QuerySet:
        if self.user_surface == 'employee':
            return employee_user_queryset(self.request)
        if self.user_surface == 'restaurant':
            return admin_user_queryset(self.request)
        return system_user_queryset(self.request)

    def get_filtered_user_queryset(self) -> QuerySet:
        filters = UserListFilters.from_request(self.request)
        if self.user_surface == 'employee':
            filters = UserListFilters(
                search=filters.search,
                role_ids=filters.role_ids,
                employment_statuses=filters.employment_statuses,
                ordering=filters.ordering,
                include_username_in_search=False,
                default_ordering=('full_name',),
            )
        return filters.apply(self.get_user_queryset())


def prevent_system_role_delete(instance: Role):
    if instance.is_system:
        raise serializers.ValidationError({'detail': _('System roles cannot be deleted.')})
