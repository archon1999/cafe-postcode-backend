from __future__ import annotations

from django.db import transaction

from apps.integrations.models import IntegrationConfig
from apps.printing.services import ensure_restaurant_templates
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation
from apps.restaurants.services.setup_readiness import restaurant_setup_readiness
from apps.restaurants.services.setup_settings import (
    canonical_settings as _canonical_settings,
    integration_fingerprint as _integration_fingerprint,
    merge_setup_settings as _merge_setup_settings,
    normalized_settings as _normalized_settings,
)


@transaction.atomic
def apply_restaurant_setup(*, restaurant, payload: dict) -> dict:
    integrations = {}
    integrations_by_fingerprint = {}

    def integration(spec, *, kind, fallback_name):
        if not spec:
            return None
        name = str(spec.get("name") or fallback_name).strip()
        provider = spec["provider"]
        obj = None
        integration_id = spec.get("id")
        if integration_id:
            obj = (
                IntegrationConfig.objects.select_for_update()
                .filter(
                    id=integration_id,
                    restaurant=restaurant,
                    kind=kind,
                )
                .first()
            )
        settings = _normalized_settings(
            kind=kind, provider=provider, settings=spec.get("settings")
        )
        if obj is not None:
            settings = _merge_setup_settings(
                kind=kind,
                provider=provider,
                current=obj.settings,
                updates=settings,
            )
        is_enabled = bool(spec.get("is_enabled", True))
        fingerprint = _integration_fingerprint(
            kind=kind,
            provider=provider,
            settings=settings,
            is_enabled=is_enabled,
        )
        if fingerprint in integrations_by_fingerprint:
            return integrations_by_fingerprint[fingerprint]

        if obj is None:
            obj = (
                IntegrationConfig.objects.filter(
                    restaurant=restaurant,
                    kind=kind,
                    provider=provider,
                    settings=settings,
                    is_enabled=is_enabled,
                )
                .order_by("created_at")
                .first()
            )
        if obj is None:
            obj = (
                IntegrationConfig.objects.filter(
                    restaurant=restaurant, kind=kind, name=name
                )
                .order_by("created_at")
                .first()
            )
        values = {
            "name": name,
            "provider": provider,
            "settings": settings,
            "is_enabled": is_enabled,
        }
        if obj is None:
            obj = IntegrationConfig.objects.create(
                restaurant=restaurant, kind=kind, **values
            )
        elif (
            _integration_fingerprint(
                kind=obj.kind,
                provider=obj.provider,
                settings=obj.settings,
                is_enabled=obj.is_enabled,
            )
            != fingerprint
        ):
            for key, value in values.items():
                setattr(obj, key, value)
            obj.save(update_fields=(*values.keys(), "updated_at"))
        integrations[str(obj.id)] = obj
        integrations_by_fingerprint[fingerprint] = obj
        return obj

    cash_desks = []
    for item in payload["cash_desks"]:
        printer = integration(
            item.get("printer"),
            kind=IntegrationConfig.Kind.PRINTER,
            fallback_name=f"{item['name']} receipt printer",
        )
        payment = integration(
            item.get("payment"),
            kind=IntegrationConfig.Kind.PAYMENT,
            fallback_name=f"{item['name']} payment",
        )
        fiscal = integration(
            item.get("fiscal"),
            kind=IntegrationConfig.Kind.FISCAL,
            fallback_name=f"{item['name']} fiscal",
        )
        desk = _update_by_id_or_first_create(
            CashDesk,
            restaurant=restaurant,
            object_id=item.get("id"),
            lookup={"restaurant": restaurant, "name": item["name"]},
            values={
                "location": item.get("location", ""),
                "enabled_payment_methods": item["enabled_payment_methods"],
                "receipt_printer_enabled": item.get("receipt_printer_enabled", True),
                "printer_integration": printer,
                "payment_integration": payment,
                "fiscal_integration": fiscal,
                "is_active": True,
            },
        )
        cash_desks.append(desk)

    prep_stations = []
    for item in payload["prep_stations"]:
        printer = integration(
            item.get("printer"),
            kind=IntegrationConfig.Kind.PRINTER,
            fallback_name=f"{item['name']} printer",
        )
        station = _update_by_id_or_first_create(
            PrepStation,
            restaurant=restaurant,
            object_id=item.get("id"),
            lookup={"restaurant": restaurant, "name": item["name"]},
            values={
                "kind": item["kind"],
                "printer_integration": printer,
                "is_active": True,
            },
        )
        prep_stations.append(station)

    if payload.get("create_takeaway", True):
        _update_first_or_create(
            DistributionPoint,
            lookup={"restaurant": restaurant, "kind": DistributionPoint.Kind.TAKEAWAY},
            values={"name": "Takeaway", "is_active": True},
        )
    _update_first_or_create(
        DistributionPoint,
        lookup={"restaurant": restaurant, "kind": DistributionPoint.Kind.DELIVERY},
        values={"name": "Delivery", "is_active": True},
    )
    templates = ensure_restaurant_templates(restaurant=restaurant)
    _delete_redundant_setup_integrations(restaurant=restaurant)
    return {
        "cashDeskIds": [str(item.id) for item in cash_desks],
        "prepStationIds": [str(item.id) for item in prep_stations],
        "integrationIds": list(integrations),
        "printTemplateIds": [str(item.id) for item in templates],
    }


def _update_first_or_create(model, *, lookup, values):
    """Idempotently repair the oldest matching row even when legacy data contains duplicates."""
    obj = (
        model.objects.select_for_update()
        .filter(**lookup)
        .order_by("created_at", "pk")
        .first()
    )
    if obj is None:
        return model.objects.create(**lookup, **values)
    changed = []
    for field, value in values.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    if changed:
        if hasattr(obj, "updated_at"):
            changed.append("updated_at")
        obj.save(update_fields=changed)
    return obj


def _update_by_id_or_first_create(model, *, restaurant, object_id, lookup, values):
    obj = None
    if object_id:
        obj = (
            model.objects.select_for_update()
            .filter(id=object_id, restaurant=restaurant)
            .first()
        )
    if obj is None:
        return _update_first_or_create(model, lookup=lookup, values=values)
    changed = []
    name = lookup.get("name")
    if name is not None and obj.name != name:
        obj.name = name
        changed.append("name")
    for field, value in values.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    if changed:
        changed.append("updated_at")
        obj.save(update_fields=changed)
    return obj


def _delete_redundant_setup_integrations(*, restaurant):
    bound_ids = set(
        CashDesk.objects.filter(restaurant=restaurant)
        .values_list(
            "printer_integration_id", "payment_integration_id", "fiscal_integration_id"
        )
        .iterator()
    )
    bound_ids = {item for row in bound_ids for item in row if item}
    bound_ids.update(
        PrepStation.objects.filter(
            restaurant=restaurant, printer_integration_id__isnull=False
        ).values_list("printer_integration_id", flat=True)
    )
    bound = list(IntegrationConfig.objects.filter(id__in=bound_ids))
    generated_suffixes = (" printer", " MARTA", " Fiscal Drive")
    for candidate in IntegrationConfig.objects.filter(restaurant=restaurant).exclude(
        id__in=bound_ids
    ):
        if not candidate.name.endswith(generated_suffixes):
            continue
        candidate_settings = _canonical_settings(candidate.settings)
        for target in bound:
            if (
                candidate.kind == target.kind
                and candidate.provider == target.provider
                and candidate.is_enabled == target.is_enabled
                and all(
                    _canonical_settings(target.settings).get(key) == value
                    for key, value in candidate_settings.items()
                )
            ):
                candidate.delete()
                break
