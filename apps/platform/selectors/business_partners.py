import secrets
import string

from django.db.models import Q
from django.utils.text import slugify

from apps.platform.helpers import get_business_partner_model, get_tariff_model
from apps.users.helpers import get_permission_model, get_role_model, get_user_model
from common.api.query_params import apply_ordering, get_bool_query_param, get_ordering_query_param, get_str_query_param

BusinessPartner = get_business_partner_model()
Permission = get_permission_model()
Role = get_role_model()
Tariff = get_tariff_model()
User = get_user_model()

BUSINESS_PARTNER_ORDERING_FIELDS = {
    'companyName': 'company_name',
    'inn': 'inn',
    'status': 'status',
    'activatedAt': 'activated_at',
}
TARIFF_ORDERING_FIELDS = {
    'name': 'name',
    'monthlyPrice': 'monthly_price',
    'yearlyPrice': 'yearly_price',
    'isActive': 'is_active',
}
RESTAURANT_LOGIN_ROLE_CODES = frozenset({'restaurant_admin', 'fast_food_admin'})
ACTIVATION_EXCLUDED_ROLE_CODES = {'product_owner', 'business_partner', 'owner'}


def generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def normalize_username_base(value: str, fallback: str) -> str:
    normalized = slugify(value or '').strip('-')
    return normalized or fallback


def generate_unique_username(base: str, exclude_user: User | None = None) -> str:
    normalized_base = normalize_username_base(base, 'user')
    username = normalized_base
    suffix = 2

    queryset = User.objects.all()
    if exclude_user is not None:
        queryset = queryset.exclude(pk=exclude_user.pk)

    while queryset.filter(username=username).exists():
        username = f'{normalized_base}-{suffix}'
        suffix += 1

    return username


def filter_partners(queryset, request):
    search = get_str_query_param(request.query_params, 'search')
    is_active = get_bool_query_param(request.query_params, 'is_active')
    ordering = get_ordering_query_param(request.query_params, BUSINESS_PARTNER_ORDERING_FIELDS)

    if search:
        queryset = queryset.filter(
            Q(company_name__icontains=search)
            | Q(legal_name__icontains=search)
            | Q(inn__icontains=search)
            | Q(phone__icontains=search)
        )
    if is_active is not None:
        queryset = queryset.filter(status=BusinessPartner.Status.ACTIVE if is_active else BusinessPartner.Status.INACTIVE)
    return apply_ordering(queryset, ordering, default_ordering=('company_name',))


def filter_tariffs(queryset, request):
    search = get_str_query_param(request.query_params, 'search')
    is_active = get_bool_query_param(request.query_params, 'is_active')
    ordering = get_ordering_query_param(request.query_params, TARIFF_ORDERING_FIELDS)

    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    return apply_ordering(queryset, ordering, default_ordering=('name',))


def get_business_partner_role() -> Role:
    return Role.objects.get(code='business_partner')


def get_restaurant_admin_role() -> Role:
    return Role.objects.get(code='restaurant_admin')


def get_fast_food_admin_role() -> Role:
    return Role.objects.get(code='fast_food_admin')


def activation_role_queryset():
    return (
        Role.objects.filter(is_system=True)
        .exclude(code__in=ACTIVATION_EXCLUDED_ROLE_CODES)
        .prefetch_related('permissions__endpoints')
        .order_by('name')
    )


def activation_permission_queryset():
    return Permission.objects.filter(roles__in=activation_role_queryset()).order_by('code').distinct()


def ensure_dashboard_permission_for_admin_roles(allowed_roles, permissions):
    allowed_roles = list(allowed_roles)
    permissions = list(permissions)

    if not any(role.code in RESTAURANT_LOGIN_ROLE_CODES for role in allowed_roles):
        return permissions

    dashboard_permission = Permission.objects.filter(code='dashboard.view').first()
    if dashboard_permission is None:
        return permissions

    permission_ids = {permission.id for permission in permissions}
    if dashboard_permission.id not in permission_ids:
        permissions.append(dashboard_permission)

    return permissions


def get_restaurant_admin_role_for_source(role_source) -> Role:
    if role_source is None:
        return get_restaurant_admin_role()

    if hasattr(role_source, 'allowed_roles'):
        role_queryset = role_source.allowed_roles.all()
    elif hasattr(role_source, 'filter'):
        role_queryset = role_source
    else:
        role_queryset = Role.objects.filter(id__in=[role.id for role in role_source])

    if role_queryset.filter(code='fast_food_admin').exists():
        return get_fast_food_admin_role()

    return get_restaurant_admin_role()
