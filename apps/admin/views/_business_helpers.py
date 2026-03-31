import secrets
import string

from django.db.models import Q
from django.utils.text import slugify

from apps.accounts.models import Role, User
from apps.organizations.models import BusinessPartner, Restaurant
from common.api.query_params import apply_ordering, get_bool_query_param, get_ordering_query_param, get_str_query_param


BUSINESS_PARTNER_ORDERING_FIELDS = {
    'companyName': 'company_name',
    'inn': 'inn',
    'status': 'status',
    'activatedAt': 'activated_at',
}
TARIFF_ORDERING_FIELDS = {
    'name': 'name',
    'classification': 'classification',
    'monthlyPrice': 'monthly_price',
    'yearlyPrice': 'yearly_price',
    'isActive': 'is_active',
}


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
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(classification__icontains=search)
            | Q(description__icontains=search)
        )
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    return apply_ordering(queryset, ordering, default_ordering=('name',))


def get_business_partner_role() -> Role:
    return Role.objects.get(code='business_partner')


def get_restaurant_admin_role() -> Role:
    return Role.objects.get(code='restaurant_admin')


def get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.select_related('business_partner').prefetch_related('entitlement', 'feature_config').order_by('name')
    if request.user.is_superuser or request.user.actor_type == User.ActorType.PRODUCT_OWNER:
        return queryset
    if request.user.actor_type == User.ActorType.BUSINESS_PARTNER and request.user.business_partner_id:
        return queryset.filter(business_partner_id=request.user.business_partner_id)
    if request.user.restaurant_id:
        return queryset.filter(pk=request.user.restaurant_id)
    return queryset.none()
