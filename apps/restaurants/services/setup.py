from __future__ import annotations

import json

from django.db import transaction

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import Hall
from apps.integrations.models import IntegrationConfig
from apps.local_agents.models import LocalAgent
from apps.printing.models import PrintTemplate
from apps.printing.presets import PRINT_KINDS
from apps.printing.services import ensure_restaurant_templates
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation
from apps.users.models import User


def _issue(code: str, message: str, *, blocking: bool) -> dict:
    return {'code': code, 'message': message, 'blocking': blocking}


def _step(step_id: str, title: str, issues: list[dict], *, metrics=None) -> dict:
    blocking = any(item['blocking'] for item in issues)
    status = 'blocked' if blocking else ('warning' if issues else 'ready')
    return {
        'id': step_id,
        'title': title,
        'status': status,
        'issues': issues,
        'metrics': metrics or {},
    }


def restaurant_setup_readiness(*, restaurant, backend_url='') -> dict:
    cash_desks = list(
        CashDesk.objects.filter(restaurant=restaurant, is_active=True).select_related(
            'printer_integration', 'payment_integration', 'fiscal_integration'
        )
    )
    prep_stations = list(
        PrepStation.objects.filter(restaurant=restaurant, is_active=True).select_related('printer_integration')
    )
    distribution_points = DistributionPoint.objects.filter(restaurant=restaurant, is_active=True)
    menu_items = CatalogItem.objects.filter(restaurant=restaurant, is_active=True)
    menu_item_count = menu_items.count()
    menu_categories = (
        CatalogCategory.objects.filter(restaurant=restaurant, is_active=True, items__is_active=True).distinct()
    )
    categories_without_station = menu_categories.filter(prep_station__isnull=True).count()
    items_without_category = menu_items.filter(category__isnull=True).count()
    users = list(
        User.objects.filter(restaurant_profile__restaurant=restaurant, is_active=True)
        .select_related('role', 'restaurant_profile')
        .distinct()
    )
    pos_users = [user for user in users if user.can_access_pos_ui]
    pin_users = [
        user
        for user in pos_users
        if user.pin_code or getattr(getattr(user, 'restaurant_profile', None), 'pin_code', '')
    ]

    profile_issues = []
    if not restaurant.is_active:
        profile_issues.append(_issue('restaurant_inactive', 'Restaurant is inactive.', blocking=True))
    for field, label in (('legal_name', 'legal name'), ('tax_number', 'tax number'), ('phone', 'phone'), ('address', 'address')):
        if not str(getattr(restaurant, field, '') or '').strip():
            profile_issues.append(_issue(f'missing_{field}', f'Restaurant {label} is not filled.', blocking=False))

    staff_issues = []
    if not pos_users:
        staff_issues.append(_issue('missing_pos_user', 'Create at least one employee with POS access.', blocking=True))
    elif not pin_users:
        staff_issues.append(_issue('missing_pos_pin', 'At least one POS employee must have a PIN.', blocking=True))

    resource_issues = []
    if not cash_desks:
        resource_issues.append(_issue('missing_cash_desk', 'Create at least one active cash desk.', blocking=True))
    if not prep_stations:
        resource_issues.append(_issue('missing_prep_station', 'Create at least one active prep station.', blocking=True))
    if not distribution_points.exists():
        resource_issues.append(_issue('missing_distribution_point', 'Create a takeaway, delivery, or hall service point.', blocking=True))

    menu_issues = []
    if menu_item_count == 0:
        menu_issues.append(_issue('empty_menu', 'Add at least one active menu item.', blocking=True))
    if categories_without_station:
        menu_issues.append(
            _issue(
                'menu_category_without_prep_station',
                f'{categories_without_station} active menu category(s) have no prep station.',
                blocking=True,
            )
        )
    if items_without_category:
        menu_issues.append(
            _issue(
                'menu_item_without_category',
                f'{items_without_category} active menu item(s) have no category.',
                blocking=True,
            )
        )

    integration_issues = []
    for cash_desk in cash_desks:
        methods = set(cash_desk.enabled_payment_methods or [])
        if cash_desk.receipt_printer_enabled and not _enabled(cash_desk.printer_integration):
            integration_issues.append(
                _issue('cash_desk_printer_missing', f'{cash_desk.name}: receipt printer is not configured.', blocking=True)
            )
        if methods & {'card', 'mixed'} and not _enabled(cash_desk.payment_integration):
            integration_issues.append(
                _issue('cash_desk_payment_missing', f'{cash_desk.name}: card payment integration is not configured.', blocking=True)
            )
        if not _enabled(cash_desk.fiscal_integration):
            integration_issues.append(
                _issue('cash_desk_fiscal_missing', f'{cash_desk.name}: fiscal integration is not configured.', blocking=False)
            )
    for station in prep_stations:
        if not _enabled(station.printer_integration):
            integration_issues.append(
                _issue('prep_station_printer_missing', f'{station.name}: kitchen printer is not configured.', blocking=False)
            )

    agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
    agent_issues = []
    if agent is None:
        agent_issues.append(_issue('local_agent_missing', 'Install and pair the site coordinator.', blocking=True))
    elif not agent.is_online():
        agent_issues.append(_issue('local_agent_offline', 'Site coordinator is currently offline.', blocking=False))

    templates = PrintTemplate.objects.filter(
        restaurant=restaurant,
        kind__in=PRINT_KINDS,
        published_version__isnull=False,
    )
    template_count = templates.values('kind').distinct().count()
    printing_issues = []
    if template_count != len(PRINT_KINDS):
        printing_issues.append(_issue('print_templates_missing', 'Publish all three canonical print templates.', blocking=True))

    steps = [
        _step('profile', 'Restaurant profile', profile_issues),
        _step('staff', 'Employees and PIN access', staff_issues, metrics={'posUsers': len(pos_users), 'pinUsers': len(pin_users)}),
        _step(
            'service_points',
            'Cash desks and service points',
            resource_issues,
            metrics={
                'cashDesks': len(cash_desks),
                'prepStations': len(prep_stations),
                'distributionPoints': distribution_points.count(),
                'halls': Hall.objects.filter(zone_or_cabin__restaurant=restaurant).count(),
            },
        ),
        _step(
            'menu',
            'Menu readiness',
            menu_issues,
            metrics={
                'items': menu_item_count,
                'categories': menu_categories.count(),
                'categoriesWithoutPrepStation': categories_without_station,
                'itemsWithoutCategory': items_without_category,
            },
        ),
        _step('integrations', 'Devices and integrations', integration_issues),
        _step('coordinator', 'Offline site coordinator', agent_issues, metrics={'installed': agent is not None, 'online': bool(agent and agent.is_online())}),
        _step('printing', 'Print templates', printing_issues, metrics={'published': template_count, 'required': len(PRINT_KINDS)}),
    ]
    blocking_count = sum(1 for step in steps for item in step['issues'] if item['blocking'])
    ready_steps = sum(1 for step in steps if step['status'] == 'ready')
    return {
        'schemaVersion': 1,
        'ready': blocking_count == 0,
        'progressPercent': round(ready_steps * 100 / len(steps)),
        'blockingIssueCount': blocking_count,
        'steps': steps,
        'quickSetup': _quick_setup_snapshot(
            restaurant=restaurant,
            cash_desks=cash_desks,
            prep_stations=prep_stations,
        ),
        'installerManifest': {
            'schemaVersion': 1,
            'restaurantId': str(restaurant.id),
            'restaurantName': restaurant.name,
            'restaurantCode': restaurant.auth_code,
            'backendUrl': backend_url.rstrip('/'),
            'coordinatorMode': True,
            'localHttpListen': '127.0.0.1:18181',
        },
    }


@transaction.atomic
def apply_restaurant_setup(*, restaurant, payload: dict) -> dict:
    integrations = {}
    integrations_by_fingerprint = {}

    def integration(spec, *, kind, fallback_name):
        if not spec:
            return None
        name = str(spec.get('name') or fallback_name).strip()
        provider = spec['provider']
        obj = None
        integration_id = spec.get('id')
        if integration_id:
            obj = IntegrationConfig.objects.select_for_update().filter(
                id=integration_id,
                restaurant=restaurant,
                kind=kind,
            ).first()
        settings = _normalized_settings(kind=kind, provider=provider, settings=spec.get('settings'))
        if obj is not None:
            settings = _merge_setup_settings(
                kind=kind,
                provider=provider,
                current=obj.settings,
                updates=settings,
            )
        is_enabled = bool(spec.get('is_enabled', True))
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
                .order_by('created_at')
                .first()
            )
        if obj is None:
            obj = IntegrationConfig.objects.filter(restaurant=restaurant, kind=kind, name=name).order_by('created_at').first()
        values = {
            'name': name,
            'provider': provider,
            'settings': settings,
            'is_enabled': is_enabled,
        }
        if obj is None:
            obj = IntegrationConfig.objects.create(restaurant=restaurant, kind=kind, **values)
        elif _integration_fingerprint(
            kind=obj.kind,
            provider=obj.provider,
            settings=obj.settings,
            is_enabled=obj.is_enabled,
        ) != fingerprint:
            for key, value in values.items():
                setattr(obj, key, value)
            obj.save(update_fields=(*values.keys(), 'updated_at'))
        integrations[str(obj.id)] = obj
        integrations_by_fingerprint[fingerprint] = obj
        return obj

    cash_desks = []
    for item in payload['cash_desks']:
        printer = integration(item.get('printer'), kind=IntegrationConfig.Kind.PRINTER, fallback_name=f"{item['name']} receipt printer")
        payment = integration(item.get('payment'), kind=IntegrationConfig.Kind.PAYMENT, fallback_name=f"{item['name']} payment")
        fiscal = integration(item.get('fiscal'), kind=IntegrationConfig.Kind.FISCAL, fallback_name=f"{item['name']} fiscal")
        desk = _update_by_id_or_first_create(
            CashDesk,
            restaurant=restaurant,
            object_id=item.get('id'),
            lookup={'restaurant': restaurant, 'name': item['name']},
            values={
                'location': item.get('location', ''),
                'enabled_payment_methods': item['enabled_payment_methods'],
                'receipt_printer_enabled': item.get('receipt_printer_enabled', True),
                'printer_integration': printer,
                'payment_integration': payment,
                'fiscal_integration': fiscal,
                'is_active': True,
            },
        )
        cash_desks.append(desk)

    prep_stations = []
    for item in payload['prep_stations']:
        printer = integration(item.get('printer'), kind=IntegrationConfig.Kind.PRINTER, fallback_name=f"{item['name']} printer")
        station = _update_by_id_or_first_create(
            PrepStation,
            restaurant=restaurant,
            object_id=item.get('id'),
            lookup={'restaurant': restaurant, 'name': item['name']},
            values={'kind': item['kind'], 'printer_integration': printer, 'is_active': True},
        )
        prep_stations.append(station)

    if payload.get('create_takeaway', True):
        _update_first_or_create(
            DistributionPoint,
            lookup={'restaurant': restaurant, 'kind': DistributionPoint.Kind.TAKEAWAY},
            values={'name': 'Takeaway', 'is_active': True},
        )
    _update_first_or_create(
        DistributionPoint,
        lookup={'restaurant': restaurant, 'kind': DistributionPoint.Kind.DELIVERY},
        values={'name': 'Delivery', 'is_active': True},
    )
    templates = ensure_restaurant_templates(restaurant=restaurant)
    _delete_redundant_setup_integrations(restaurant=restaurant)
    return {
        'cashDeskIds': [str(item.id) for item in cash_desks],
        'prepStationIds': [str(item.id) for item in prep_stations],
        'integrationIds': list(integrations),
        'printTemplateIds': [str(item.id) for item in templates],
    }


def _normalized_settings(*, kind, provider, settings):
    values = _canonical_settings(settings)
    if provider in {'windows-raw', 'marta-softpos', 'fiscal-drive-service'}:
        values['transport'] = 'local-agent'
    if kind == IntegrationConfig.Kind.PRINTER:
        values.setdefault('encoding', 'cp1251')
        values.setdefault('code_page', 46)
    return values


def _canonical_settings(settings):
    values = dict(settings or {})
    aliases = {
        'endpointUrl': 'endpoint_url',
        'taxNumber': 'tax_number',
        'connectionType': 'connection_type',
        'printerName': 'printer_name',
        'codePage': 'code_page',
        'paperWidthMm': 'paper_width_mm',
        'cutAfterPrint': 'cut_after_print',
        'terminalId': 'terminal_id',
        'factoryId': 'factory_id',
    }
    for alias, canonical in aliases.items():
        if alias in values:
            values[canonical] = values.pop(alias)
    return values


def _merge_setup_settings(*, kind, provider, current, updates):
    values = _canonical_settings(current)
    values.update(_canonical_settings(updates))
    if kind == IntegrationConfig.Kind.PRINTER:
        if values.get('connection_type') == 'socket':
            values.pop('printer_name', None)
        elif values.get('connection_type') == 'system_printer':
            values.pop('host', None)
            values.pop('port', None)
    return _normalized_settings(kind=kind, provider=provider, settings=values)


def _read_setting(config, *keys):
    if config is None:
        return ''
    settings = _canonical_settings(config.settings)
    for key in keys:
        value = settings.get(key)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _printer_target(config):
    if config is None:
        return ''
    settings = _canonical_settings(config.settings)
    if settings.get('connection_type') == 'socket' or settings.get('host'):
        host = str(settings.get('host') or '').strip()
        port = int(settings.get('port') or 9100)
        return f'{host}:{port}' if host and port != 9100 else host
    return str(settings.get('printer_name') or '').strip()


def _quick_setup_snapshot(*, restaurant, cash_desks, prep_stations):
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
        .order_by('-is_enabled', 'created_at')
    )

    fiscal = next((item.fiscal_integration for item in cash_desks if item.fiscal_integration_id), None)
    payment = next((item.payment_integration for item in cash_desks if item.payment_integration_id), None)
    if fiscal is None:
        fiscal = IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            is_enabled=True,
        ).order_by('created_at').first()
    if payment is None:
        payment = IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            is_enabled=True,
        ).order_by('created_at').first()

    cash_desk_values = []
    for item in cash_desks:
        printer = item.printer_integration
        cash_desk_values.append(
            {
                'id': str(item.id),
                'name': item.name,
                'printerTarget': _printer_target(printer),
                'printerIntegrationId': str(printer.id) if printer else '',
                'paymentIntegrationId': str(item.payment_integration_id or (payment.id if payment else '')),
                'fiscalIntegrationId': str(item.fiscal_integration_id or (fiscal.id if fiscal else '')),
            }
        )

    prep_station_values = []
    for item in prep_stations:
        printer = item.printer_integration
        if printer is None and spare_printers:
            printer = spare_printers.pop(0)
        prep_station_values.append(
            {
                'id': str(item.id),
                'name': item.name,
                'kind': item.kind,
                'printerTarget': _printer_target(printer),
                'printerIntegrationId': str(printer.id) if printer else '',
            }
        )

    return {
        'taxNumber': _read_setting(fiscal, 'tax_number')
        or _read_setting(payment, 'tax_number')
        or str(restaurant.tax_number or '').strip(),
        'martaAddress': _read_setting(payment, 'endpoint_url'),
        'cashDesks': cash_desk_values,
        'prepStations': prep_station_values,
    }


def _integration_fingerprint(*, kind, provider, settings, is_enabled):
    return (
        str(kind),
        str(provider),
        bool(is_enabled),
        json.dumps(settings or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
    )


def _update_first_or_create(model, *, lookup, values):
    """Idempotently repair the oldest matching row even when legacy data contains duplicates."""
    obj = model.objects.select_for_update().filter(**lookup).order_by('created_at', 'pk').first()
    if obj is None:
        return model.objects.create(**lookup, **values)
    changed = []
    for field, value in values.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    if changed:
        if hasattr(obj, 'updated_at'):
            changed.append('updated_at')
        obj.save(update_fields=changed)
    return obj


def _update_by_id_or_first_create(model, *, restaurant, object_id, lookup, values):
    obj = None
    if object_id:
        obj = model.objects.select_for_update().filter(id=object_id, restaurant=restaurant).first()
    if obj is None:
        return _update_first_or_create(model, lookup=lookup, values=values)
    changed = []
    name = lookup.get('name')
    if name is not None and obj.name != name:
        obj.name = name
        changed.append('name')
    for field, value in values.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    if changed:
        changed.append('updated_at')
        obj.save(update_fields=changed)
    return obj


def _delete_redundant_setup_integrations(*, restaurant):
    bound_ids = set(
        CashDesk.objects.filter(restaurant=restaurant)
        .values_list('printer_integration_id', 'payment_integration_id', 'fiscal_integration_id')
        .iterator()
    )
    bound_ids = {item for row in bound_ids for item in row if item}
    bound_ids.update(
        PrepStation.objects.filter(restaurant=restaurant, printer_integration_id__isnull=False).values_list(
            'printer_integration_id', flat=True
        )
    )
    bound = list(IntegrationConfig.objects.filter(id__in=bound_ids))
    generated_suffixes = (' printer', ' MARTA', ' Fiscal Drive')
    for candidate in IntegrationConfig.objects.filter(restaurant=restaurant).exclude(id__in=bound_ids):
        if not candidate.name.endswith(generated_suffixes):
            continue
        candidate_settings = _canonical_settings(candidate.settings)
        for target in bound:
            if (
                candidate.kind == target.kind
                and candidate.provider == target.provider
                and candidate.is_enabled == target.is_enabled
                and all(_canonical_settings(target.settings).get(key) == value for key, value in candidate_settings.items())
            ):
                candidate.delete()
                break


def _enabled(config):
    return bool(config and config.is_enabled)
