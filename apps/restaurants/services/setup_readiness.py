from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import Hall
from apps.local_agents.models import LocalAgent
from apps.printing.models import PrintTemplate
from apps.printing.presets import PRINT_KINDS
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation
from apps.restaurants.services.setup_readiness_checks import (
    agent_issues,
    integration_issues,
    menu_issues,
    printing_issues,
    profile_issues,
    service_point_issues,
    staff_issues,
)
from apps.restaurants.services.setup_snapshot import quick_setup_snapshot
from apps.users.models import User


def _step(step_id: str, title: str, issues: list[dict], *, metrics=None) -> dict:
    blocking = any(item["blocking"] for item in issues)
    status = "blocked" if blocking else ("warning" if issues else "ready")
    return {
        "id": step_id,
        "title": title,
        "status": status,
        "issues": issues,
        "metrics": metrics or {},
    }


def restaurant_setup_readiness(*, restaurant, backend_url="") -> dict:
    cash_desks = list(
        CashDesk.objects.filter(restaurant=restaurant, is_active=True).select_related(
            "printer_integration", "payment_integration", "fiscal_integration"
        )
    )
    prep_stations = list(
        PrepStation.objects.filter(
            restaurant=restaurant, is_active=True
        ).select_related("printer_integration")
    )
    distribution_points = DistributionPoint.objects.filter(
        restaurant=restaurant, is_active=True
    )
    menu_items = CatalogItem.objects.filter(restaurant=restaurant, is_active=True)
    menu_item_count = menu_items.count()
    menu_categories = CatalogCategory.objects.filter(
        restaurant=restaurant, is_active=True, items__is_active=True
    ).distinct()
    categories_without_station = menu_categories.filter(
        prep_station__isnull=True
    ).count()
    items_without_category = menu_items.filter(category__isnull=True).count()

    users = list(
        User.objects.filter(restaurant_profile__restaurant=restaurant, is_active=True)
        .select_related("role", "restaurant_profile")
        .distinct()
    )
    pos_users = [user for user in users if user.can_access_pos_ui]
    pin_users = [
        user
        for user in pos_users
        if user.pin_code
        or getattr(getattr(user, "restaurant_profile", None), "pin_code", "")
    ]
    agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
    template_count = (
        PrintTemplate.objects.filter(
            restaurant=restaurant,
            kind__in=PRINT_KINDS,
            published_version__isnull=False,
        )
        .values("kind")
        .distinct()
        .count()
    )

    steps = [
        _step("profile", "Restaurant profile", profile_issues(restaurant)),
        _step(
            "staff",
            "Employees and PIN access",
            staff_issues(pos_users, pin_users),
            metrics={"posUsers": len(pos_users), "pinUsers": len(pin_users)},
        ),
        _step(
            "service_points",
            "Cash desks and service points",
            service_point_issues(
                cash_desks=cash_desks,
                prep_stations=prep_stations,
                has_distribution_points=distribution_points.exists(),
            ),
            metrics={
                "cashDesks": len(cash_desks),
                "prepStations": len(prep_stations),
                "distributionPoints": distribution_points.count(),
                "halls": Hall.objects.filter(
                    zone_or_cabin__restaurant=restaurant
                ).count(),
            },
        ),
        _step(
            "menu",
            "Menu readiness",
            menu_issues(
                item_count=menu_item_count,
                categories_without_station=categories_without_station,
                items_without_category=items_without_category,
            ),
            metrics={
                "items": menu_item_count,
                "categories": menu_categories.count(),
                "categoriesWithoutPrepStation": categories_without_station,
                "itemsWithoutCategory": items_without_category,
            },
        ),
        _step(
            "integrations",
            "Devices and integrations",
            integration_issues(cash_desks=cash_desks, prep_stations=prep_stations),
        ),
        _step(
            "coordinator",
            "Offline site coordinator",
            agent_issues(agent),
            metrics={
                "installed": agent is not None,
                "online": bool(agent and agent.is_online()),
            },
        ),
        _step(
            "printing",
            "Print templates",
            printing_issues(
                template_count=template_count, required_count=len(PRINT_KINDS)
            ),
            metrics={"published": template_count, "required": len(PRINT_KINDS)},
        ),
    ]
    blocking_count = sum(
        1 for step in steps for item in step["issues"] if item["blocking"]
    )
    ready_steps = sum(1 for step in steps if step["status"] == "ready")
    return {
        "schemaVersion": 1,
        "ready": blocking_count == 0,
        "progressPercent": round(ready_steps * 100 / len(steps)),
        "blockingIssueCount": blocking_count,
        "steps": steps,
        "quickSetup": quick_setup_snapshot(
            restaurant=restaurant,
            cash_desks=cash_desks,
            prep_stations=prep_stations,
        ),
        "installerManifest": {
            "schemaVersion": 2,
            "restaurantId": str(restaurant.id),
            "restaurantName": restaurant.name,
            "backendUrl": backend_url.rstrip("/"),
            "coordinatorMode": True,
            "pairingMode": "device_qr",
            "localHttpListen": "127.0.0.1:18181",
        },
    }
