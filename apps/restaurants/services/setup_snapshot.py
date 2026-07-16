from apps.integrations.models import IntegrationConfig
from apps.restaurants.services.setup_settings import printer_target, read_setting


def quick_setup_snapshot(*, restaurant, cash_desks, prep_stations):
    bound_printer_ids = {
        item.printer_integration_id
        for item in [*cash_desks, *prep_stations]
        if item.printer_integration_id
    }
    spare_printers = list(
        IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
        )
        .exclude(id__in=bound_printer_ids)
        .order_by("-is_enabled", "created_at")
    )

    fiscal = next(
        (item.fiscal_integration for item in cash_desks if item.fiscal_integration_id),
        None,
    )
    payment = next(
        (
            item.payment_integration
            for item in cash_desks
            if item.payment_integration_id
        ),
        None,
    )
    if fiscal is None:
        fiscal = (
            IntegrationConfig.objects.filter(
                restaurant=restaurant,
                kind=IntegrationConfig.Kind.FISCAL,
                is_enabled=True,
            )
            .order_by("created_at")
            .first()
        )
    if payment is None:
        payment = (
            IntegrationConfig.objects.filter(
                restaurant=restaurant,
                kind=IntegrationConfig.Kind.PAYMENT,
                is_enabled=True,
            )
            .order_by("created_at")
            .first()
        )

    cash_desk_values = []
    for item in cash_desks:
        printer = item.printer_integration
        cash_desk_values.append(
            {
                "id": str(item.id),
                "name": item.name,
                "printerTarget": printer_target(printer),
                "printerIntegrationId": str(printer.id) if printer else "",
                "paymentIntegrationId": str(
                    item.payment_integration_id or (payment.id if payment else "")
                ),
                "fiscalIntegrationId": str(
                    item.fiscal_integration_id or (fiscal.id if fiscal else "")
                ),
            }
        )

    prep_station_values = []
    for item in prep_stations:
        printer = item.printer_integration
        if printer is None and spare_printers:
            printer = spare_printers.pop(0)
        prep_station_values.append(
            {
                "id": str(item.id),
                "name": item.name,
                "kind": item.kind,
                "printerTarget": printer_target(printer),
                "printerIntegrationId": str(printer.id) if printer else "",
            }
        )

    return {
        "taxNumber": read_setting(fiscal, "tax_number")
        or read_setting(payment, "tax_number")
        or str(restaurant.tax_number or "").strip(),
        "martaAddress": read_setting(payment, "endpoint_url"),
        "cashDesks": cash_desk_values,
        "prepStations": prep_station_values,
    }
