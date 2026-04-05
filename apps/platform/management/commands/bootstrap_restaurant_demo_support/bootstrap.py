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
from .specs import ORDER_SPECS_BY_RESTAURANT, RESTAURANT_SPECS, TARIFF_SPECS


def bootstrap_demo(command) -> None:
    seed_system_roles_and_permissions()
    roles_by_code = get_roles_by_code()

    seed_top_level_users(roles_by_code)
    tariffs = seed_tariffs(TARIFF_SPECS, roles_by_code)

    partner = upsert_business_partner()
    partner_credentials = activate_business_partner_user(partner)

    for restaurant_spec in RESTAURANT_SPECS:
        restaurant = upsert_restaurant(partner, restaurant_spec)
        reset_restaurant_seed(restaurant)
        entitlement = configure_entitlement(restaurant, tariffs[restaurant_spec.tariff_key])
        admin_credentials = activate_restaurant_admin_user(restaurant, entitlement.tariff)

        setup_entities = seed_setup_entities(restaurant, restaurant_spec.key)
        halls_by_code, tables_by_key = seed_halls_and_tables(restaurant, restaurant_spec.hall_enabled)
        items_by_code = seed_catalog(
            restaurant,
            restaurant_spec.key,
            setup_entities['prep_stations'],
        )
        users_by_username = seed_staff(
            restaurant,
            restaurant_spec.key,
            roles_by_code,
            halls_by_code,
        )

        seed_orders(
            restaurant=restaurant,
            order_specs=ORDER_SPECS_BY_RESTAURANT[restaurant_spec.key],
            users_by_username=users_by_username,
            items_by_code=items_by_code,
            halls_by_code=halls_by_code,
            tables_by_key=tables_by_key,
            cash_desk=setup_entities['cash_desk'],
            distribution_points=setup_entities['distribution_points'],
        )

        command.stdout.write(
            command.style.SUCCESS(
                f"Seeded {restaurant.name} ({admin_credentials.username} / {admin_credentials.password})"
            )
        )

    command.stdout.write(
        command.style.SUCCESS(
            f"Business partner owner: {partner_credentials.username} / {partner_credentials.password}"
        )
    )
