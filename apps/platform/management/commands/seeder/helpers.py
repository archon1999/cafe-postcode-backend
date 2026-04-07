from dataclasses import dataclass

from django.apps import apps as django_apps
from django.db.models import Q
from django.utils import timezone

from apps.users.models import RestaurantProfile, Role, User
from apps.users.signals.seed_default_roles import seed_default_roles_signal
from apps.platform.selectors.business_partners import (
    generate_password,
    generate_unique_username,
    get_business_partner_role,
    get_restaurant_admin_role_for_source,
    normalize_username_base,
)
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, ZoneOrCabin
from apps.integrations.services import ensure_mock_configs
from apps.platform.models import BusinessPartner, RestaurantEntitlement, Tariff
from apps.platform.services import add_billing_period
from apps.restaurants.models import CashDesk, Device, DistributionPoint, PrepStation, Restaurant

from .specs import (
    BUSINESS_PARTNER_SPEC,
    TOP_LEVEL_USERS,
)


@dataclass(frozen=True)
class GeneratedCredentials:
    username: str
    password: str


def seed_system_roles_and_permissions() -> None:
    seed_default_roles_signal(sender=django_apps.get_app_config('users'))


def get_roles_by_code() -> dict[str, Role]:
    return {role.code: role for role in Role.objects.filter(is_system=True).prefetch_related('permissions')}


def derive_permission_ids(role_codes: tuple[str, ...] | list[str], roles_by_code: dict[str, Role]) -> list[str]:
    permission_ids: set[str] = set()
    for role_code in role_codes:
        role = roles_by_code[role_code]
        permission_ids.update(role.permissions.values_list('id', flat=True))
    return sorted(permission_ids)


def seed_top_level_users(roles_by_code: dict[str, Role]) -> dict[str, User]:
    admin_user, _ = User.objects.get_or_create(
        username=TOP_LEVEL_USERS['superadmin']['username'],
        defaults={
            'full_name': TOP_LEVEL_USERS['superadmin']['full_name'],
            'is_staff': True,
            'is_superuser': True,
        },
    )
    admin_user.full_name = TOP_LEVEL_USERS['superadmin']['full_name']
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.role = None
    admin_user.set_password(TOP_LEVEL_USERS['superadmin']['password'])
    admin_user.save()

    product_owner_user, _ = User.objects.get_or_create(
        username=TOP_LEVEL_USERS['product_owner']['username'],
        defaults={
            'full_name': TOP_LEVEL_USERS['product_owner']['full_name'],
            'is_staff': True,
            'role': roles_by_code['product_owner'],
        },
    )
    product_owner_user.full_name = TOP_LEVEL_USERS['product_owner']['full_name']
    product_owner_user.is_staff = True
    product_owner_user.is_superuser = False
    product_owner_user.role = roles_by_code['product_owner']
    product_owner_user.set_password(TOP_LEVEL_USERS['product_owner']['password'])
    product_owner_user.save()

    return {
        'superadmin': admin_user,
        'product_owner': product_owner_user,
    }


def cleanup_legacy_demo_tariffs() -> None:
    Tariff.objects.filter(name__in=['Fast food', 'Printer kitchen', 'Full service', 'Demo tarif']).delete()


def cleanup_legacy_demo_restaurants() -> None:
    Restaurant.objects.filter(name='Postcode kafe').delete()


def seed_tariffs(tariff_specs, roles_by_code: dict[str, Role]) -> dict[str, Tariff]:
    cleanup_legacy_demo_tariffs()
    tariffs: dict[str, Tariff] = {}

    for spec in tariff_specs:
        tariff, _ = Tariff.objects.get_or_create(
            name=spec.name,
            defaults={
                'description': spec.description,
                'monthly_price': spec.monthly_price,
                'yearly_price': spec.yearly_price,
                'is_active': True,
            },
        )
        tariff.description = spec.description
        tariff.monthly_price = spec.monthly_price
        tariff.yearly_price = spec.yearly_price
        tariff.is_active = True
        tariff.save()
        tariff.allowed_roles.set([roles_by_code[role_code] for role_code in spec.role_codes])
        tariff.permissions.set(derive_permission_ids(spec.role_codes, roles_by_code))
        tariffs[spec.key] = tariff

    return tariffs


def upsert_business_partner() -> BusinessPartner:
    partner, _ = BusinessPartner.objects.get_or_create(
        inn=BUSINESS_PARTNER_SPEC['inn'],
        defaults={
            'company_name': BUSINESS_PARTNER_SPEC['company_name'],
            'legal_name': BUSINESS_PARTNER_SPEC['legal_name'],
            'director_name': BUSINESS_PARTNER_SPEC['director_name'],
            'phone': BUSINESS_PARTNER_SPEC['phone'],
            'email': BUSINESS_PARTNER_SPEC['email'],
            'address': BUSINESS_PARTNER_SPEC['address'],
            'status': BusinessPartner.Status.ACTIVE,
        },
    )
    partner.company_name = BUSINESS_PARTNER_SPEC['company_name']
    partner.legal_name = BUSINESS_PARTNER_SPEC['legal_name']
    partner.director_name = BUSINESS_PARTNER_SPEC['director_name']
    partner.phone = BUSINESS_PARTNER_SPEC['phone']
    partner.email = BUSINESS_PARTNER_SPEC['email']
    partner.address = BUSINESS_PARTNER_SPEC['address']
    partner.status = BusinessPartner.Status.ACTIVE
    partner.activated_at = timezone.now()
    partner.deactivated_at = None
    partner.save()
    return partner


def activate_business_partner_user(partner: BusinessPartner) -> GeneratedCredentials:
    password = generate_password()
    user = partner.owner_user
    username = generate_unique_username(f'bh-{partner.inn}', exclude_user=user)

    if user is None:
        user = User.objects.create(
            username=username,
            full_name=partner.company_name,
            phone=partner.phone,
            role=get_business_partner_role(),
            is_active=True,
            is_staff=True,
        )
    else:
        user.username = username
        user.full_name = partner.company_name
        user.phone = partner.phone
        user.role = get_business_partner_role()
        user.is_active = True
        user.is_staff = True

    user.set_password(password)
    user.save()
    partner.owner_user = user
    partner.activated_at = timezone.now()
    partner.deactivated_at = None
    partner.status = BusinessPartner.Status.ACTIVE
    partner.save(update_fields=['owner_user', 'activated_at', 'deactivated_at', 'status', 'updated_at'])
    return GeneratedCredentials(username=user.username, password=password)


def reset_restaurant_seed(restaurant: Restaurant) -> None:
    user_ids = list(
        User.objects.filter(restaurant_profile__restaurant=restaurant)
        .distinct()
        .values_list('id', flat=True)
    )
    restaurant.kitchen_tickets.all().delete()
    restaurant.orders.all().delete()
    restaurant.table_sessions.all().delete()
    restaurant.cash_desks.all().delete()
    restaurant.devices.all().delete()
    restaurant.prep_stations.all().delete()
    DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant).delete()
    Hall.objects.filter(zone_or_cabin__restaurant=restaurant).delete()
    restaurant.catalog_items.all().delete()
    restaurant.catalog_categories.all().delete()
    restaurant.distribution_points.all().delete()
    restaurant.zones.all().delete()
    if user_ids:
        User.objects.filter(id__in=user_ids).delete()
    restaurant.last_order_number = 0
    restaurant.save(update_fields=['last_order_number', 'updated_at'])


def upsert_restaurant(partner: BusinessPartner, spec) -> Restaurant:
    cleanup_legacy_demo_restaurants()
    restaurant, _ = Restaurant.objects.get_or_create(
        name=spec.name,
        defaults={
            'business_partner': partner,
            'legal_name': spec.legal_name,
            'tax_number': spec.tax_number,
            'phone': spec.phone,
            'address': spec.address,
            'service_fee_percent': spec.service_fee_percent,
            'is_active': True,
        },
    )
    restaurant.business_partner = partner
    restaurant.legal_name = spec.legal_name
    restaurant.tax_number = spec.tax_number
    restaurant.phone = spec.phone
    restaurant.address = spec.address
    restaurant.service_fee_percent = spec.service_fee_percent
    restaurant.is_active = True
    restaurant.activated_at = timezone.now()
    restaurant.deactivated_at = None
    restaurant.save()
    return restaurant


def configure_entitlement(restaurant: Restaurant, tariff: Tariff) -> RestaurantEntitlement:
    entitlement, _ = RestaurantEntitlement.objects.get_or_create(restaurant=restaurant)
    entitlement.tariff = tariff
    entitlement.is_custom = False
    entitlement.is_active = True
    entitlement.starts_on = timezone.localdate()
    entitlement.billing_period = RestaurantEntitlement.BillingPeriod.MONTHLY
    entitlement.expires_on = add_billing_period(entitlement.starts_on, entitlement.billing_period)
    entitlement.monthly_price = tariff.monthly_price
    entitlement.yearly_price = tariff.yearly_price
    entitlement.save()
    entitlement.permissions.clear()
    entitlement.allowed_roles.clear()
    ensure_mock_configs(restaurant)
    return entitlement


def activate_restaurant_admin_user(restaurant: Restaurant, tariff: Tariff) -> GeneratedCredentials:
    password = generate_password()
    admin_user = User.objects.filter(
        restaurant_profile__restaurant=restaurant,
        role__code__in=('restaurant_admin', 'fast_food_admin'),
    ).order_by('created_at').first()
    admin_username = generate_unique_username(
        f"admin-{normalize_username_base(restaurant.name, 'restaurant')}",
        exclude_user=admin_user,
    )
    admin_role = get_restaurant_admin_role_for_source(tariff)

    if admin_user is None:
        admin_user = User.objects.create(
            username=admin_username,
            full_name=f'{restaurant.name} Admin',
            phone=restaurant.phone,
            role=admin_role,
            is_active=True,
            is_staff=True,
        )
    else:
        admin_user.username = admin_username
        admin_user.full_name = f'{restaurant.name} Admin'
        admin_user.phone = restaurant.phone
        admin_user.role = admin_role
        admin_user.is_active = True
        admin_user.is_staff = True

    admin_user.set_password(password)
    admin_user.save()
    RestaurantProfile.objects.update_or_create(
        user=admin_user,
        defaults={'restaurant': restaurant},
    )
    return GeneratedCredentials(username=admin_user.username, password=password)


def seed_setup_entities(restaurant: Restaurant, setup_spec, halls_by_code: dict[str, Hall]):
    prep_stations = {}
    for spec in setup_spec.prep_stations:
        station, _ = PrepStation.objects.get_or_create(
            restaurant=restaurant,
            name=spec.name,
            defaults={'kind': spec.kind},
        )
        station.kind = spec.kind
        station.is_active = True
        station.save()
        prep_stations[spec.code] = station

    cash_desk, _ = CashDesk.objects.get_or_create(
        restaurant=restaurant,
        name=setup_spec.cash_desk_name,
        defaults={'location': setup_spec.cash_desk_location},
    )
    cash_desk.location = setup_spec.cash_desk_location
    cash_desk.is_active = True
    cash_desk.save()

    distribution_points = {}
    for spec in setup_spec.distribution_points:
        point, _ = DistributionPoint.objects.get_or_create(
            restaurant=restaurant,
            name=spec.name,
            defaults={'kind': spec.kind},
        )
        point.kind = spec.kind
        point.is_active = True
        point.assigned_hall = halls_by_code.get(spec.assigned_hall_code) if spec.assigned_hall_code else None
        point.save()
        distribution_points[spec.kind] = point

    devices = []
    for spec in setup_spec.devices:
        device, _ = Device.objects.get_or_create(
            restaurant=restaurant,
            name=spec.name,
            defaults={'mode': spec.mode},
        )
        device.mode = spec.mode
        device.primary_hall = halls_by_code.get(spec.primary_hall_code) if spec.primary_hall_code else None
        device.is_active = True
        device.save()
        device.allowed_halls.set([halls_by_code[code] for code in spec.allowed_hall_codes if code in halls_by_code])
        devices.append(device)

    return {
        'prep_stations': prep_stations,
        'cash_desk': cash_desk,
        'distribution_points': distribution_points,
        'devices': devices,
    }


def attach_restaurant_profile(
    user: User,
    restaurant: Restaurant,
    *,
    hall_switch_permission: bool = False,
    primary_hall=None,
    allowed_halls=None,
    pin: str | None = None,
) -> None:
    profile, _ = RestaurantProfile.objects.update_or_create(
        user=user,
        defaults={
            'restaurant': restaurant,
            'hall_switch_permission': hall_switch_permission,
            'primary_hall': primary_hall,
        },
    )
    profile.allowed_halls.set(allowed_halls or [])
    if pin:
        user.set_pin(pin)
    else:
        user.pin_code = ''
        user.save(update_fields=['pin_code'])
        profile.pin_code = ''
        profile.save(update_fields=['pin_code'])


def seed_halls_and_tables(restaurant: Restaurant, floor_spec):
    if floor_spec is None:
        return {}, {}

    zones_by_code = {}
    for zone_spec in floor_spec.zones:
        zone, _ = ZoneOrCabin.objects.get_or_create(
            restaurant=restaurant,
            name=zone_spec.name,
            defaults={'sort_order': zone_spec.sort_order, 'is_active': True},
        )
        zone.sort_order = zone_spec.sort_order
        zone.is_active = True
        zone.save()
        zones_by_code[zone_spec.code] = zone

    halls = {}
    tables = {}
    for spec in floor_spec.halls:
        zone = zones_by_code[spec.zone_code]
        hall, _ = Hall.objects.get_or_create(
            zone_or_cabin=zone,
            name=spec.name,
            defaults={
                'description': spec.description,
                'grid_columns': 8,
                'sort_order': spec.sort_order,
                'is_active': True,
            },
        )
        hall.description = spec.description
        hall.grid_columns = 8
        hall.sort_order = spec.sort_order
        hall.is_active = True
        hall.save()
        halls[spec.code] = hall

        for table_spec in spec.tables:
            table, _ = DiningTable.objects.get_or_create(
                hall=hall,
                table_number=table_spec.table_number,
                defaults={
                    'zone': zone,
                    'name': table_spec.name,
                    'seat_count': table_spec.seat_count,
                    'shape': DiningTable.Shape.SQUARE,
                    'shape_variant': DiningTable.get_default_shape_variant(table_spec.seat_count),
                    'status': table_spec.status,
                    'position_x': table_spec.position_x,
                    'position_y': table_spec.position_y,
                    'width': table_spec.width,
                    'height': table_spec.height,
                },
            )
            table.zone = zone
            table.name = table_spec.name
            table.seat_count = table_spec.seat_count
            table.shape = DiningTable.Shape.SQUARE
            table.shape_variant = DiningTable.get_default_shape_variant(table_spec.seat_count)
            table.status = table_spec.status
            table.position_x = table_spec.position_x
            table.position_y = table_spec.position_y
            table.width = table_spec.width
            table.height = table_spec.height
            table.save()
            tables[(spec.code, table_spec.table_number)] = table

    return halls, tables


def seed_catalog(restaurant: Restaurant, catalog_specs, prep_stations: dict[str, PrepStation]):
    items_by_code = {}

    for category_index, category_spec in enumerate(catalog_specs, start=1):
        category, _ = CatalogCategory.objects.get_or_create(
            restaurant=restaurant,
            mxik_code=category_spec.category_code,
            defaults={'name': category_spec.category_name, 'sort_order': category_index},
        )
        category.name = category_spec.category_name
        category.mxik_name = category_spec.category_mxik_name
        category.image_url = category_spec.image_url
        category.image_source = CatalogCategory.ImageSource.MXIK_CACHE if category.image_url else ''
        category.sort_order = category_index
        category.is_active = True
        category.save()

        for item_spec in category_spec.items:
            item, _ = CatalogItem.objects.get_or_create(
                restaurant=restaurant,
                name=item_spec.name,
                defaults={
                    'category': category,
                    'prep_station': prep_stations.get(item_spec.prep_station_code),
                    'price': item_spec.price,
                },
            )
            item.category = category
            item.prep_station = prep_stations.get(item_spec.prep_station_code)
            item.price = item_spec.price
            item.description = item_spec.description
            item.is_active = True
            item.is_stoplisted = False
            item.mxik_code = item_spec.mxik_code
            item.mxik_name = item_spec.mxik_name
            item.save()
            items_by_code[item_spec.code] = item

    return items_by_code


def seed_staff(restaurant: Restaurant, staff_specs, roles_by_code: dict[str, Role], halls_by_code: dict[str, Hall]):
    users_by_username = {}
    for spec in staff_specs:
        user, _ = User.objects.get_or_create(
            username=spec.username,
            defaults={
                'full_name': spec.full_name,
                'role': roles_by_code[spec.role_code],
                'is_active': True,
            },
        )
        user.full_name = spec.full_name
        user.phone = restaurant.phone
        user.role = roles_by_code[spec.role_code]
        user.is_active = True
        user.is_staff = spec.surface == 'admin'

        if spec.password:
            user.set_password(spec.password)
        else:
            user.set_unusable_password()

        user.save()

        allowed_halls = [halls_by_code[code] for code in spec.allowed_hall_codes if code in halls_by_code]
        primary_hall = halls_by_code.get(spec.primary_hall_code) if spec.primary_hall_code else None
        attach_restaurant_profile(
            user,
            restaurant,
            hall_switch_permission=bool(allowed_halls),
            primary_hall=primary_hall,
            allowed_halls=allowed_halls,
            pin=spec.pin,
        )
        users_by_username[spec.username] = user

    return users_by_username
