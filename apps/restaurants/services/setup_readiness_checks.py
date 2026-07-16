def _issue(code: str, message: str, *, blocking: bool) -> dict:
    return {"code": code, "message": message, "blocking": blocking}


def profile_issues(restaurant) -> list[dict]:
    issues = []
    if not restaurant.is_active:
        issues.append(
            _issue("restaurant_inactive", "Restaurant is inactive.", blocking=True)
        )
    for field, label in (
        ("legal_name", "legal name"),
        ("tax_number", "tax number"),
        ("phone", "phone"),
        ("address", "address"),
    ):
        if not str(getattr(restaurant, field, "") or "").strip():
            issues.append(
                _issue(
                    f"missing_{field}",
                    f"Restaurant {label} is not filled.",
                    blocking=False,
                )
            )
    return issues


def staff_issues(pos_users, pin_users) -> list[dict]:
    if not pos_users:
        return [
            _issue(
                "missing_pos_user",
                "Create at least one employee with POS access.",
                blocking=True,
            )
        ]
    if not pin_users:
        return [
            _issue(
                "missing_pos_pin",
                "At least one POS employee must have a PIN.",
                blocking=True,
            )
        ]
    return []


def service_point_issues(
    *, cash_desks, prep_stations, has_distribution_points
) -> list[dict]:
    issues = []
    if not cash_desks:
        issues.append(
            _issue(
                "missing_cash_desk",
                "Create at least one active cash desk.",
                blocking=True,
            )
        )
    if not prep_stations:
        issues.append(
            _issue(
                "missing_prep_station",
                "Create at least one active prep station.",
                blocking=True,
            )
        )
    if not has_distribution_points:
        issues.append(
            _issue(
                "missing_distribution_point",
                "Create a takeaway, delivery, or hall service point.",
                blocking=True,
            )
        )
    return issues


def menu_issues(
    *, item_count, categories_without_station, items_without_category
) -> list[dict]:
    issues = []
    if item_count == 0:
        issues.append(
            _issue("empty_menu", "Add at least one active menu item.", blocking=True)
        )
    if categories_without_station:
        issues.append(
            _issue(
                "menu_category_without_prep_station",
                f"{categories_without_station} active menu category(s) have no prep station.",
                blocking=True,
            )
        )
    if items_without_category:
        issues.append(
            _issue(
                "menu_item_without_category",
                f"{items_without_category} active menu item(s) have no category.",
                blocking=True,
            )
        )
    return issues


def integration_issues(*, cash_desks, prep_stations) -> list[dict]:
    issues = []
    for cash_desk in cash_desks:
        methods = set(cash_desk.enabled_payment_methods or [])
        if cash_desk.receipt_printer_enabled and not _enabled(
            cash_desk.printer_integration
        ):
            issues.append(
                _issue(
                    "cash_desk_printer_missing",
                    f"{cash_desk.name}: receipt printer is not configured.",
                    blocking=True,
                )
            )
        if methods & {"card", "mixed"} and not _enabled(cash_desk.payment_integration):
            issues.append(
                _issue(
                    "cash_desk_payment_missing",
                    f"{cash_desk.name}: card payment integration is not configured.",
                    blocking=False,
                )
            )
        if not _enabled(cash_desk.fiscal_integration):
            issues.append(
                _issue(
                    "cash_desk_fiscal_missing",
                    f"{cash_desk.name}: fiscal integration is not configured.",
                    blocking=False,
                )
            )
    for station in prep_stations:
        if not _enabled(station.printer_integration):
            issues.append(
                _issue(
                    "prep_station_printer_missing",
                    f"{station.name}: kitchen printer is not configured.",
                    blocking=False,
                )
            )
    return issues


def agent_issues(agent) -> list[dict]:
    if agent is None:
        return [
            _issue(
                "local_agent_missing",
                "Install and pair the site coordinator.",
                blocking=True,
            )
        ]
    if not agent.is_online():
        return [
            _issue(
                "local_agent_offline",
                "Site coordinator is currently offline.",
                blocking=True,
            )
        ]
    return []


def printing_issues(*, template_count, required_count) -> list[dict]:
    if template_count == required_count:
        return []
    return [
        _issue(
            "print_templates_missing",
            "Publish all three canonical print templates.",
            blocking=True,
        )
    ]


def _enabled(config):
    return bool(config and config.is_enabled)
