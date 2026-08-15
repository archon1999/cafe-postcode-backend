from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import PosCatalogItemSerializer
from apps.catalog.utils.marking import item_marking_gtin, item_requires_marking, normalized_gtin_candidates
from apps.sales.helpers import get_order_item_marking_model, get_order_item_model
from apps.catalog.utils.prep_station import resolve_order_item_prep_station
from apps.sales.services.state import OrderStateService

OrderItem = get_order_item_model()
OrderItemMarking = get_order_item_marking_model()


@dataclass(frozen=True)
class ParsedMarkingCode:
    raw_code: str
    gtin: str = ''
    serial: str = ''


def parse_marking_code(raw_code: str) -> ParsedMarkingCode:
    raw = str(raw_code or '').strip()
    if raw.startswith('01') and len(raw) >= 16 and raw[2:16].isdigit():
        gtin = raw[2:16]
        tail = raw[16:]
        if tail.startswith('21'):
            return ParsedMarkingCode(raw_code=raw, gtin=gtin, serial=tail[2:])
        return ParsedMarkingCode(raw_code=raw, gtin=gtin, serial=tail)
    if raw.isdigit() and len(raw) >= 8:
        return ParsedMarkingCode(raw_code=raw, gtin=raw[:14] if len(raw) >= 14 else raw)
    return ParsedMarkingCode(raw_code=raw)


def find_catalog_item_by_marking(*, restaurant, parsed: ParsedMarkingCode):
    if not parsed.raw_code:
        raise ValidationError({'rawCode': _('Scanner code is empty.')})
    gtin_candidates = normalized_gtin_candidates(parsed.gtin)
    if not gtin_candidates:
        raise ValidationError({'rawCode': _('Scanner code does not contain GTIN.')})

    direct = CatalogItem.objects.filter(restaurant=restaurant, is_active=True, marking_gtin__in=gtin_candidates).first()
    if direct:
        return direct

    for item in CatalogItem.objects.filter(restaurant=restaurant, is_active=True).only(
        'id',
        'name',
        'marking_gtin',
        'mxik_payload',
        'requires_marking',
    ):
        if normalized_gtin_candidates(item_marking_gtin(item)) & gtin_candidates:
            return item
    raise ValidationError({'rawCode': _('No catalog item matches this marking code.')})


def serialize_catalog_scan(*, restaurant, raw_code: str):
    parsed = parse_marking_code(raw_code)
    item = find_catalog_item_by_marking(restaurant=restaurant, parsed=parsed)
    return {
        'raw_code': parsed.raw_code,
        'rawCode': parsed.raw_code,
        'gtin': parsed.gtin,
        'serial': parsed.serial,
        'item': PosCatalogItemSerializer(item).data,
    }


def marking_status(order):
    items = (
        order.items.exclude(status=OrderItem.Status.CANCELLED)
        .select_related('catalog_item')
        .prefetch_related('markings')
    )
    rows = []
    missing_total = 0
    for item in items:
        required = int(item.quantity) if item_requires_marking(item.catalog_item) else 0
        scanned = item.markings.count() if required else 0
        missing = max(required - scanned, 0)
        if required or scanned:
            rows.append(
                {
                    'order_item_id': str(item.id),
                    'catalog_item_id': str(item.catalog_item_id),
                    'catalog_item_name': item.catalog_item.name,
                    'required': required,
                    'scanned': scanned,
                    'missing': missing,
                    'markings': [
                        {
                            'id': str(marking.id),
                            'raw_code': marking.raw_code,
                            'rawCode': marking.raw_code,
                            'gtin': marking.gtin,
                            'serial': marking.serial,
                            'scanned_at': marking.scanned_at,
                        }
                        for marking in item.markings.all()
                    ],
                }
            )
        missing_total += missing
    return {'missing_count': missing_total, 'missingCount': missing_total, 'items': rows}


def validate_order_markings(order):
    if not getattr(order.restaurant, 'marking_check_enabled', False):
        return marking_status(order)

    status = marking_status(order)
    if status['missing_count']:
        raise ValidationError({'markings': _('Marked products must be scanned before payment.'), 'details': status})
    return status


class OrderMarkingScanService:
    state_service_class = OrderStateService

    @transaction.atomic
    def scan(self, *, order, raw_code: str, scanned_by, mode: str = 'add'):
        order = type(order).objects.select_for_update().select_related('restaurant').get(pk=order.pk)
        if order.status not in {order.Status.OPEN, order.Status.SUBMITTED, order.Status.READY}:
            raise ValidationError({'detail': _('This order cannot be changed.')})

        parsed = parse_marking_code(raw_code)
        catalog_item = (
            CatalogItem.objects.select_related('category__prep_station', 'prep_station')
            .filter(pk=find_catalog_item_by_marking(restaurant=order.restaurant, parsed=parsed).pk)
            .get()
        )
        normalized_mode = str(mode or 'add').strip().lower()

        if normalized_mode == 'remove':
            order_item, kitchen_tickets, kitchen_print_documents = self._remove_matching_order_item(
                order=order,
                catalog_item=catalog_item,
                raw_code=parsed.raw_code,
                scanned_by=scanned_by,
            )
            order.recalculate_totals()

            from apps.kitchen.services import sync_order_tickets

            sync_order_tickets(order)
            return {
                'order_item': order_item,
                'marking': None,
                'status': marking_status(order),
                'kitchen_tickets': kitchen_tickets,
                'kitchen_print_documents': kitchen_print_documents,
            }

        if OrderItemMarking.objects.filter(order_item__order__restaurant=order.restaurant, raw_code=parsed.raw_code).exists():
            raise ValidationError({'rawCode': _('This marking code has already been scanned.')})

        order_item = None
        if normalized_mode in {'add', 'attach'}:
            order_item = self._find_missing_order_item(order=order, catalog_item=catalog_item)

        if normalized_mode == 'attach':
            if order_item is None:
                raise ValidationError({'rawCode': _('This marked product is not present in the order or is already fully scanned.')})

        if order_item is None:
            base_unit_price = int(catalog_item.price or 0)
            order_item = OrderItem.objects.create(
                order=order,
                catalog_item=catalog_item,
                created_by=scanned_by,
                quantity=1,
                sale_unit=catalog_item.sale_unit,
                base_unit_price=base_unit_price,
                unit_price=base_unit_price,
                prep_station=resolve_order_item_prep_station(catalog_item=catalog_item, restaurant=order.restaurant),
            )

        marking = None
        if item_requires_marking(catalog_item):
            marking = OrderItemMarking.objects.create(
                order_item=order_item,
                catalog_item=catalog_item,
                raw_code=parsed.raw_code,
                gtin=parsed.gtin,
                serial=parsed.serial,
                scanned_by=scanned_by,
            )
        order.recalculate_totals()

        from apps.kitchen.services import sync_order_tickets

        sync_order_tickets(order)
        return {
            'order_item': order_item,
            'marking': marking,
            'status': marking_status(order),
            'kitchen_tickets': [],
            'kitchen_print_documents': [],
        }

    @staticmethod
    def _find_missing_order_item(*, order, catalog_item):
        candidates = (
            order.items.select_for_update()
            .filter(catalog_item=catalog_item)
            .exclude(status=OrderItem.Status.CANCELLED)
            .prefetch_related('markings')
            .order_by('created_at')
        )
        for item in candidates:
            if item.markings.count() < item.quantity:
                return item
        return None

    def _remove_matching_order_item(self, *, order, catalog_item, raw_code: str, scanned_by):
        from apps.kitchen.models import KitchenTicket, KitchenTicketLine

        matching_marking = (
            OrderItemMarking.objects.select_for_update()
            .filter(order_item__order=order, catalog_item=catalog_item, raw_code=raw_code)
            .exclude(order_item__status=OrderItem.Status.CANCELLED)
            .select_related('order_item')
            .first()
        )
        if matching_marking is not None:
            order_item = order.items.select_for_update().get(pk=matching_marking.order_item_id)
            matching_marking.delete()
        else:
            candidates = (
                order.items.select_for_update()
                .filter(catalog_item=catalog_item)
                .exclude(status=OrderItem.Status.CANCELLED)
                .prefetch_related('markings')
                .order_by('-created_at')
            )
            order_item = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.markings.count() < candidate.quantity
                ),
                None,
            )

        if order_item is None:
            raise ValidationError({'rawCode': _('This marked product is not present in the order.')})

        original_ticket_line = (
            KitchenTicketLine.objects.select_for_update()
            .select_related('ticket')
            .filter(order_item=order_item)
            .first()
        )
        original_order_item_id = order_item.pk
        active_order_item = self.state_service_class().remove_order_item(
            order_item=order_item,
            one_unit=True,
        )
        kitchen_tickets = []
        if active_order_item.pk != original_order_item_id:
            from apps.kitchen.services import dispatch_order_tickets

            kitchen_tickets = dispatch_order_tickets(
                order,
                created_by=scanned_by or active_order_item.created_by or order.opened_by,
                order_item_ids=[active_order_item.pk],
                create_sale_print_documents=False,
            )

        kitchen_print_documents = []
        if (
            original_ticket_line is not None
            and original_ticket_line.ticket.routed_via
            in (KitchenTicket.RouteMode.PRINTER, KitchenTicket.RouteMode.BOTH)
        ):
            from apps.printing.services import create_kitchen_cancellation_print_document

            cancellation_document, _snapshot = create_kitchen_cancellation_print_document(
                ticket=original_ticket_line.ticket,
                order_item=order_item,
                quantity_delta=-1,
                created_by=scanned_by or order_item.created_by or order.opened_by,
            )
            kitchen_print_documents.append(cancellation_document)

        return active_order_item, kitchen_tickets, kitchen_print_documents
