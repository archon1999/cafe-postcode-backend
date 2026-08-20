from dataclasses import dataclass

from django.db.models import (
    Count,
    DateTimeField,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import CatalogItem
from apps.devices.models import Device
from apps.restaurants.helpers import (
    get_cash_desk_model,
    get_distribution_point_model,
    get_prep_station_model,
    get_restaurant_model,
)
from apps.users.helpers import get_user_model
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_query_param,
)

CashDesk = get_cash_desk_model()
DistributionPoint = get_distribution_point_model()
PrepStation = get_prep_station_model()
Restaurant = get_restaurant_model()
User = get_user_model()

OPERATIONAL_DEVICE_TYPES = (
    Device.Type.POS_TERMINAL,
    Device.Type.LOCAL_AGENT,
    Device.Type.TV_MONITOR,
)
INACTIVE_EMPLOYMENT_STATUSES = ('inactive', 'archived')

RESTAURANT_ORDERING_FIELDS = {
    'name': 'name',
    'legalName': 'legal_name',
    'phone': 'phone',
    'currency': 'currency',
    'isActive': 'is_active',
    'activatedAt': 'activated_at',
    'deactivatedAt': 'deactivated_at',
    'createdAt': 'created_at',
    'updatedAt': 'updated_at',
    'parentName': 'parent_restaurant__name',
    'branchCount': 'branch_count',
    'activeUsersCount': 'active_users_count',
    'activeDeviceCount': 'active_device_count',
    'onlineDeviceCount': 'online_device_count',
    'lastSeenAt': 'last_seen_at',
}


def _count_subquery(queryset, group_field: str):
    return Coalesce(
        Subquery(
            queryset.order_by()
            .values(group_field)
            .annotate(value=Count('pk'))
            .values('value')[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def with_restaurant_list_annotations(
    queryset: QuerySet,
    *,
    branch_queryset: QuerySet | None = None,
) -> QuerySet:
    if branch_queryset is None:
        branch_queryset = Restaurant.objects.all()
    active_users = User.objects.filter(
        restaurant_profile__restaurant_id=OuterRef('pk'),
        is_active=True,
    ).exclude(
        employee_profile__employment_status__in=INACTIVE_EMPLOYMENT_STATUSES
    )
    operational_devices = Device.objects.filter(
        restaurant_id=OuterRef('pk'),
        type__in=OPERATIONAL_DEVICE_TYPES,
    )
    active_devices = operational_devices.filter(
        status=Device.Status.ACTIVE,
        revoked_at__isnull=True,
    )
    online_devices = active_devices.filter(lease_expires_at__gt=timezone.now())

    return queryset.annotate(
        branch_count=_count_subquery(
            branch_queryset.filter(parent_restaurant_id=OuterRef('pk')),
            'parent_restaurant_id',
        ),
        active_users_count=_count_subquery(
            active_users,
            'restaurant_profile__restaurant_id',
        ),
        active_device_count=_count_subquery(active_devices, 'restaurant_id'),
        online_device_count=_count_subquery(online_devices, 'restaurant_id'),
        last_seen_at=Subquery(
            active_devices.filter(last_seen_at__isnull=False)
            .order_by('-last_seen_at')
            .values('last_seen_at')[:1],
            output_field=DateTimeField(),
        ),
    )


def with_restaurant_detail_annotations(
    queryset: QuerySet,
    *,
    branch_queryset: QuerySet | None = None,
) -> QuerySet:
    queryset = with_restaurant_list_annotations(
        queryset,
        branch_queryset=branch_queryset,
    )
    return queryset.annotate(
        active_cash_desks_count=_count_subquery(
            CashDesk.objects.filter(
                restaurant_id=OuterRef('pk'),
                is_active=True,
            ),
            'restaurant_id',
        ),
        active_prep_stations_count=_count_subquery(
            PrepStation.objects.filter(
                restaurant_id=OuterRef('pk'),
                is_active=True,
            ),
            'restaurant_id',
        ),
        active_distribution_points_count=_count_subquery(
            DistributionPoint.objects.filter(
                restaurant_id=OuterRef('pk'),
                is_active=True,
            ),
            'restaurant_id',
        ),
        active_menu_items_count=_count_subquery(
            CatalogItem.objects.filter(
                restaurant_id=OuterRef('pk'),
                is_active=True,
            ),
            'restaurant_id',
        ),
    )


def get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.select_related(
        'business_partner',
        'parent_restaurant',
        'entitlement',
        'entitlement__tariff',
    ).prefetch_related(
        'entitlement__permissions',
        'entitlement__allowed_roles',
        'entitlement__tariff__permissions',
        'entitlement__tariff__allowed_roles',
    ).order_by('name')
    if request.user.is_superuser or request.user.role_code == 'product_owner':
        return queryset

    business_partner = request.user.get_business_partner_scope()
    if business_partner is not None:
        return queryset.filter(
            Q(parent_restaurant__isnull=True)
            | Q(parent_restaurant__business_partner_id=business_partner.id),
            business_partner_id=business_partner.id,
        )

    return queryset.none()


@dataclass(frozen=True)
class RestaurantListFilters:
    search: str = ''
    is_active: bool | None = None
    branch_type: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'RestaurantListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            branch_type=get_str_query_param(query_params, 'branch_type').lower(),
            ordering=get_ordering_query_param(query_params, RESTAURANT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet, *, with_ordering: bool = True) -> QuerySet:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(legal_name__icontains=self.search)
                | Q(tax_number__icontains=self.search)
                | Q(phone__icontains=self.search)
                | Q(address__icontains=self.search)
                | Q(parent_restaurant__name__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        if self.branch_type == 'root':
            queryset = queryset.filter(parent_restaurant__isnull=True)
        elif self.branch_type == 'branch':
            queryset = queryset.filter(parent_restaurant__isnull=False)
        if not with_ordering:
            return queryset
        return apply_ordering(queryset, self.ordering, default_ordering=('name',))


def get_restaurant_portfolio_summary(queryset: QuerySet) -> dict:
    active_access = Q(is_active=True, entitlement__is_active=True)
    inactive_access = Q(entitlement__isnull=True) | Q(entitlement__is_active=False)
    access_mismatch = (
        Q(is_active=True)
        & inactive_access
    ) | Q(is_active=False, entitlement__is_active=True)

    counts = queryset.order_by().aggregate(
        total_count=Count('pk'),
        root_count=Count('pk', filter=Q(parent_restaurant__isnull=True)),
        branch_count=Count('pk', filter=Q(parent_restaurant__isnull=False)),
        active_count=Count('pk', filter=active_access),
        inactive_count=Count(
            'pk',
            filter=(
                Q(is_active=False, activated_at__isnull=False)
                & inactive_access
            ),
        ),
        draft_count=Count(
            'pk',
            filter=Q(is_active=False, activated_at__isnull=True),
        ),
        access_mismatch_count=Count('pk', filter=access_mismatch),
        without_tariff_count=Count(
            'pk',
            filter=Q(entitlement__isnull=True) | Q(entitlement__tariff__isnull=True),
        ),
    )
    restaurant_ids = queryset.order_by().values('pk')
    counts['active_users_count'] = (
        User.objects.filter(
            restaurant_profile__restaurant_id__in=restaurant_ids,
            is_active=True,
        )
        .exclude(employee_profile__employment_status__in=INACTIVE_EMPLOYMENT_STATUSES)
        .distinct()
        .count()
    )
    device_counts = Device.objects.filter(
        restaurant_id__in=restaurant_ids,
        type__in=OPERATIONAL_DEVICE_TYPES,
    ).aggregate(
        active_device_count=Count(
            'pk',
            filter=Q(
                status=Device.Status.ACTIVE,
                revoked_at__isnull=True,
            ),
        ),
        online_device_count=Count(
            'pk',
            filter=Q(
                status=Device.Status.ACTIVE,
                revoked_at__isnull=True,
                lease_expires_at__gt=timezone.now(),
            ),
        ),
    )
    return {**counts, **device_counts}
