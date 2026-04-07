from .helpers import (
    activate_business_partner_user,
    activate_restaurant_admin_user,
    configure_entitlement,
    get_roles_by_code,
    reset_restaurant_seed,
    seed_catalog,
    seed_halls_and_tables,
    seed_setup_entities,
    seed_staff,
    seed_system_roles_and_permissions,
    seed_tariffs,
    seed_top_level_users,
    upsert_business_partner,
    upsert_restaurant,
)
from .orders import seed_orders
from .specs import RESTAURANT_SPECS, TARIFF_SPECS, TOP_LEVEL_USERS


def bootstrap_demo(command) -> None:
    seed_system_roles_and_permissions()
    roles_by_code = get_roles_by_code()
    seed_top_level_users(roles_by_code)
    tariffs = seed_tariffs(TARIFF_SPECS, roles_by_code)
    partner = upsert_business_partner()
    partner_credentials = activate_business_partner_user(partner)

    restaurant_credentials: dict[str, tuple[str, str, str, list[tuple[str, str]]]] = {}

    for restaurant_spec in RESTAURANT_SPECS:
        restaurant = upsert_restaurant(partner, restaurant_spec)
        reset_restaurant_seed(restaurant)
        tariff = tariffs[restaurant_spec.tariff_key]
        configure_entitlement(restaurant, tariff)

        halls_by_code, tables_by_key = seed_halls_and_tables(restaurant, restaurant_spec.floor)
        setup = seed_setup_entities(restaurant, restaurant_spec.setup, halls_by_code)
        items_by_code = seed_catalog(restaurant, restaurant_spec.catalog, setup['prep_stations'])
        admin_credentials = activate_restaurant_admin_user(restaurant, tariff)
        staff_users = seed_staff(restaurant, restaurant_spec.staff, roles_by_code, halls_by_code)
        seed_orders(
            restaurant=restaurant,
            restaurant_spec=restaurant_spec,
            users_by_username=staff_users,
            items_by_code=items_by_code,
            halls_by_code=halls_by_code,
            tables_by_key=tables_by_key,
            cash_desk=setup['cash_desk'],
            distribution_points=setup['distribution_points'],
        )
        restaurant_credentials[restaurant_spec.name] = (
            admin_credentials.username,
            admin_credentials.password,
            restaurant.auth_code,
            [(spec.username, spec.pin) for spec in restaurant_spec.staff if spec.pin],
        )

    command.stdout.write(command.style.SUCCESS('Restaurant demo bootstrap complete.'))
    command.stdout.write(f"superadmin: {TOP_LEVEL_USERS['superadmin']['username']} / {TOP_LEVEL_USERS['superadmin']['password']}")
    command.stdout.write(
        f"product_owner: {TOP_LEVEL_USERS['product_owner']['username']} / {TOP_LEVEL_USERS['product_owner']['password']}"
    )
    command.stdout.write(f'business_partner: {partner_credentials.username} / {partner_credentials.password}')
    for restaurant_name, (username, password, auth_code, staff_pins) in restaurant_credentials.items():
        command.stdout.write(f'{restaurant_name} admin: {username} / {password} / auth_code: {auth_code}')
        if staff_pins:
            formatted_staff_pins = ', '.join(f'{staff_username}={pin}' for staff_username, pin in staff_pins)
            command.stdout.write(f'{restaurant_name} staff pins: {formatted_staff_pins}')
