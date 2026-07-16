from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden
from apps.sales.models import OrderItem

from .unikassa_types import FiscalReceiptPart, UnikassaFiscalError


class UnikassaReceiptPayloadMixin:
    def _build_receipt_parts(self, *, order, payment) -> list[FiscalReceiptPart]:
        order_items = list(
            order.items.exclude(status=OrderItem.Status.CANCELLED)
            .select_related('catalog_item', 'catalog_item__category')
            .order_by('created_at', 'id')
        )
        if not order_items:
            raise UnikassaFiscalError('Order has no active items for fiscal receipt registration.')

        fiscal_cash, fiscal_card = self._fiscal_payment_amounts(payment=payment)
        if payment.method in {payment.Method.CARD, payment.Method.QR} and fiscal_cash <= 0:
            return [
                FiscalReceiptPart(
                    order_items,
                    self._service_fee(order=order),
                    self._pay_type_for_amounts(cash_amount=fiscal_cash, card_amount=fiscal_card),
                    'none',
                    fiscal_cash,
                    fiscal_card,
                )
            ]

        restricted = [
            item
            for item in order_items
            if is_catalog_item_cash_sale_forbidden(item)
        ]
        normal = [item for item in order_items if item not in restricted]
        if not restricted:
            return [
                FiscalReceiptPart(
                    normal,
                    self._service_fee(order=order),
                    self._pay_type_for_amounts(cash_amount=fiscal_cash, card_amount=fiscal_card),
                    'none',
                    fiscal_cash,
                    fiscal_card,
                )
            ]
        if not normal:
            restricted_total = sum(int(item.line_total or 0) for item in restricted) + self._service_fee(order=order)
            return [
                FiscalReceiptPart(
                    restricted,
                    self._service_fee(order=order),
                    'card',
                    'cash_forbidden_category',
                    0,
                    restricted_total,
                )
            ]

        normal_fee, restricted_fee = self._split_service_fee(order=order, normal_items=normal, restricted_items=restricted)
        normal_total = sum(int(item.line_total or 0) for item in normal) + normal_fee
        restricted_total = sum(int(item.line_total or 0) for item in restricted) + restricted_fee
        normal_cash = min(fiscal_cash, normal_total)
        normal_card = max(normal_total - normal_cash, 0)
        return [
            FiscalReceiptPart(
                normal,
                normal_fee,
                self._pay_type_for_amounts(cash_amount=normal_cash, card_amount=normal_card),
                'mixed_cash_allowed_items',
                normal_cash,
                normal_card,
            ),
            FiscalReceiptPart(restricted, restricted_fee, 'card', 'cash_forbidden_category', 0, restricted_total),
        ]

    def _pay_type(self, payment) -> str:
        if payment.method == payment.Method.CASH:
            return 'cash'
        if payment.method in {payment.Method.CARD, payment.Method.QR}:
            return 'card'
        return 'card'

    def _fiscal_payment_amounts(self, *, payment) -> tuple[int, int]:
        fiscal_cash = int(getattr(payment, 'fiscal_cash_amount', 0) or 0)
        fiscal_card = int(getattr(payment, 'fiscal_card_amount', 0) or 0)
        if fiscal_cash or fiscal_card:
            return fiscal_cash, fiscal_card
        if payment.method == payment.Method.CASH:
            return int(payment.amount or 0), 0
        if payment.method in {payment.Method.CARD, payment.Method.QR}:
            return 0, int(payment.amount or 0)
        if payment.method == payment.Method.MIXED:
            return int(getattr(payment, 'cash_amount', 0) or 0), int(getattr(payment, 'card_amount', 0) or 0)
        return 0, int(payment.amount or 0)

    @staticmethod
    def _pay_type_for_amounts(*, cash_amount: int, card_amount: int) -> str:
        return 'card' if int(card_amount or 0) > 0 else 'cash'

    @staticmethod
    def _service_fee(*, order) -> int:
        return max(int(order.total or 0) - int(order.subtotal or 0), 0)

    def _split_service_fee(self, *, order, normal_items: list, restricted_items: list) -> tuple[int, int]:
        service_fee = self._service_fee(order=order)
        if service_fee <= 0:
            return 0, 0
        normal_total = sum(int(item.line_total or 0) for item in normal_items)
        restricted_total = sum(int(item.line_total or 0) for item in restricted_items)
        subtotal = normal_total + restricted_total
        if subtotal <= 0:
            return service_fee, 0
        normal_fee = int((Decimal(service_fee) * Decimal(normal_total) / Decimal(subtotal)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        return normal_fee, service_fee - normal_fee

    def _build_sale_receipt(self, *, order, payment, part: FiscalReceiptPart, memory_info: dict | None) -> dict:
        items = self._build_sale_items(order=order, items=part.items, service_fee=part.service_fee)
        total = sum(int(item['Price'] or 0) for item in items)
        received_cash = self._money_to_fiscal(part.received_cash) if part.received_cash is not None else total if part.pay_type == 'cash' else 0
        received_card = self._money_to_fiscal(part.received_card) if part.received_card is not None else 0 if part.pay_type == 'cash' else total
        receipt_payload = {
            'Time': self._format_operation_time(self._next_operation_datetime(memory_info)),
            'Type': 0,
            'Operation': 0,
            'ReceivedCash': received_cash,
            'ReceivedCard': received_card,
            'RefundInfo': None,
            'Items': items,
        }
        location = self._location_payload()
        if location:
            receipt_payload['Location'] = location
        extra_info = self._extra_info(order=order, payment=payment)
        if extra_info:
            receipt_payload['ExtraInfo'] = extra_info
        return receipt_payload

    def _build_sale_items(self, *, order, items: list, service_fee: int) -> list[dict]:
        payload_items = []
        vat_percent = self._vat_percent(order=order)
        for item in items:
            labels = self._extract_labels(item=item)
            if labels:
                unit_price = int((Decimal(item.line_total or 0) / Decimal(max(int(item.quantity or 1), 1))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                for label in labels:
                    item_payload = {
                        'Name': str(getattr(item.catalog_item, 'name', '') or item.catalog_item.mxik_name or 'Item')[:128],
                        'Amount': 1000,
                        'Price': self._money_to_fiscal(unit_price),
                        'Discount': 0,
                        'Other': 0,
                        'OwnerType': 0,
                        'PackageCode': self._extract_package_code(item=item),
                        'Barcode': self._extract_barcode(item=item),
                        'Labels': [label],
                        'VAT': 0,
                        'VATPercent': 0,
                    }
                    self._apply_vat(item_payload, amount=unit_price, percent=vat_percent)
                    self._apply_item_classification(item_payload, item=item)
                    payload_items.append(item_payload)
                continue

            item_payload = {
                'Name': str(getattr(item.catalog_item, 'name', '') or item.catalog_item.mxik_name or 'Item')[:128],
                'Amount': int(item.quantity or 0) * 1000,
                'Price': self._money_to_fiscal(item.line_total),
                'Discount': 0,
                'Other': 0,
                'OwnerType': 0,
                'PackageCode': self._extract_package_code(item=item),
                'Barcode': self._extract_barcode(item=item),
                'Labels': self._extract_labels(item=item),
                'VAT': 0,
                'VATPercent': 0,
            }
            self._apply_vat(item_payload, amount=item.line_total, percent=vat_percent)
            self._apply_item_classification(item_payload, item=item)
            payload_items.append(item_payload)

        if service_fee:
            service_payload = {
                'Name': 'Xizmat haqi',
                'Amount': 1000,
                'Price': self._money_to_fiscal(service_fee),
                'Discount': 0,
                'Other': 0,
                'OwnerType': 0,
                'PackageCode': '',
                'Barcode': '',
                'Labels': [],
                'VAT': 0,
                'VATPercent': 0,
                'SPIC': '',
            }
            units = self._default_unit_code()
            if units is not None:
                service_payload['Units'] = units
            self._apply_vat(service_payload, amount=service_fee, percent=vat_percent)
            payload_items.append(service_payload)
        return payload_items

    def _apply_item_classification(self, item_payload: dict, *, item):
        spic = str(
            getattr(item.catalog_item, 'mxik_code', '')
            or getattr(getattr(item.catalog_item, 'category', None), 'mxik_code', '')
            or ''
        ).strip()
        item_payload['SPIC'] = spic
        units = self._extract_units(item=item)
        if units is not None:
            item_payload['Units'] = units

    def _parse_registered_datetime(self, value):
        parsed = self._parse_operation_time(value)
        return parsed.isoformat() if parsed is not None else timezone.now().isoformat()

    def _next_operation_datetime(self, memory_info: dict | None):
        candidate = timezone.localtime(timezone.now()).replace(microsecond=0)
        last_operation = self._parse_operation_time((memory_info or {}).get('LastOperationTime'))
        if last_operation is not None:
            candidate = max(candidate, last_operation + timedelta(seconds=1))
        return candidate

    def _parse_operation_time(self, value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return timezone.localtime(parsed).replace(microsecond=0)

    def _format_operation_time(self, value) -> str:
        return timezone.localtime(value).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    def _format_refund_datetime(self, value: str) -> str:
        parsed = self._parse_operation_time(value)
        if parsed is None:
            digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
            if len(digits) != 14:
                raise UnikassaFiscalError('Original fiscal receipt DateTime is invalid for refund registration.')
            return digits
        return timezone.localtime(parsed).strftime('%Y%m%d%H%M%S')

    def _build_refund_info(self, response_payload: dict) -> dict:
        terminal_id = str(response_payload.get('TerminalID') or '').strip()
        receipt_seq = response_payload.get('ReceiptSeq')
        fiscal_sign = str(response_payload.get('FiscalSign') or '').strip()
        date_time = str(response_payload.get('DateTime') or '').strip()
        if not terminal_id or receipt_seq in (None, '') or not fiscal_sign or not date_time:
            raise UnikassaFiscalError('Original receipt payload is missing fields required for refund registration.')
        return {
            'TerminalID': terminal_id,
            'ReceiptSeq': int(receipt_seq),
            'DateTime': self._format_refund_datetime(date_time),
            'FiscalSign': fiscal_sign,
        }

    def _vat_percent(self, *, order) -> Decimal:
        if not bool(getattr(order.restaurant, 'vat_enabled', False)):
            return Decimal('0')
        try:
            return max(Decimal(str(getattr(order.restaurant, 'vat_percent', 0) or 0)), Decimal('0'))
        except Exception:
            return Decimal('0')

    def _apply_vat(self, item_payload: dict, *, amount, percent: Decimal):
        if percent <= 0:
            return
        fiscal_amount = self._money_to_fiscal(amount)
        item_payload['VATPercent'] = int(percent.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        item_payload['VAT'] = int((Decimal(fiscal_amount) * percent / (Decimal('100') + percent)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def _extract_units(self, *, item) -> int | None:
        value = self._find_first(
            [
                getattr(getattr(item, 'catalog_item', None), 'mxik_payload', None),
                getattr(getattr(getattr(item, 'catalog_item', None), 'category', None), 'mxik_payload', None),
            ],
            {'unit_code', 'unitCode', 'common_unit_code', 'commonUnitCode', 'units', 'Units', 'unit', 'Unit'},
        )
        try:
            return int(value) if value not in (None, '') else self._default_unit_code()
        except (TypeError, ValueError):
            return self._default_unit_code()

    def _default_unit_code(self) -> int | None:
        try:
            value = int(self.settings.get('default_unit_code') or self.settings.get('defaultUnitCode') or 796)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _extract_barcode(self, *, item) -> str:
        value = self._find_first(
            [
                getattr(getattr(item, 'catalog_item', None), 'mxik_payload', None),
                getattr(getattr(getattr(item, 'catalog_item', None), 'category', None), 'mxik_payload', None),
            ],
            {'barcode', 'Barcode', 'bar_code', 'barCode', 'international_code', 'internationalCode', 'gtin', 'GTIN'},
        )
        return ''.join(ch for ch in str(value or '') if ch.isdigit())[:64]

    def _extract_package_code(self, *, item) -> str:
        value = self._find_first(
            [
                getattr(getattr(item, 'catalog_item', None), 'mxik_payload', None),
                getattr(getattr(getattr(item, 'catalog_item', None), 'category', None), 'mxik_payload', None),
            ],
            {'package_code', 'packageCode', 'PackageCode', 'package', 'Package'},
        )
        return str(value or '').strip()[:64]

    def _extract_labels(self, *, item) -> list[str]:
        labels = []
        markings = getattr(item, '_prefetched_objects_cache', {}).get('markings')
        if markings is None and getattr(item, 'pk', None):
            markings = item.markings.all()
        if markings is not None:
            labels.extend(str(marking.raw_code).strip() for marking in markings if str(marking.raw_code or '').strip())
        for payload in [getattr(item, 'metadata', None), getattr(item, 'payload', None), getattr(item, 'extra', None), getattr(item, 'note', None)]:
            value = self._find_first(payload, {'labels', 'Labels', 'marking_codes', 'markingCodes', 'marking_code', 'markingCode', 'label', 'Label'})
            if isinstance(value, list):
                labels.extend(str(entry).strip() for entry in value if str(entry or '').strip())
            elif value:
                labels.append(str(value).strip())
        return list(dict.fromkeys(labels))[:300]

    def _find_first(self, payload, keys: set[str]):
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys:
                    return value
                nested = self._find_first(value, keys)
                if nested not in (None, ''):
                    return nested
        if isinstance(payload, list):
            for item in payload:
                nested = self._find_first(item, keys)
                if nested not in (None, ''):
                    return nested
        return None

    @staticmethod
    def _money_to_fiscal(value) -> int:
        return int(value or 0) * 100

    def _location_payload(self) -> dict | None:
        latitude = self.settings.get('latitude')
        longitude = self.settings.get('longitude')
        if latitude in (None, '') or longitude in (None, ''):
            return None
        try:
            return {'Latitude': float(latitude), 'Longitude': float(longitude)}
        except (TypeError, ValueError):
            return None

    def _extra_info(self, *, order, payment) -> dict:
        tax_number = self.settings.get('tax_number') or self.settings.get('taxNumber') or getattr(order.restaurant, 'tax_number', '')
        if not tax_number:
            return {}
        return {
            'CarNumber': '',
            'CardNumber': '',
            'CardType': 0,
            'CashedOutFromCard': 0,
            'PINFL': '',
            'PPTID': '',
            'PhoneNumber': '',
            'QRPaymentID': '',
            'QRPaymentProvider': 0,
            'TIN': str(tax_number).strip(),
        }

