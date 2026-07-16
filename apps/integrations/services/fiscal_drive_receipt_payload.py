from decimal import Decimal, ROUND_HALF_UP

from apps.sales.models import OrderItem

from .fiscal_drive_types import FiscalDriveError


class FiscalDriveReceiptPayloadMixin:
    def _build_sale_receipt(self, *, order, payment, memory_info: dict | None) -> dict:
        total = int(order.total or 0)
        payment_amount = int(payment.amount or 0)
        if payment_amount - total > 10_000:
            raise FiscalDriveError(
                'Payment amount exceeds the fiscal receipt total by more than 100 sum. '
                'Use exact-payment amounts for live fiscal receipts.'
            )

        receipt_time = self._format_operation_time(self._next_operation_datetime(memory_info))
        items = self._build_sale_items(order=order)
        received_cash, received_card = self._received_amounts(payment=payment)
        payload = {
            'Time': receipt_time,
            'Type': 0,
            'Operation': 0,
            'ReceivedCash': received_cash,
            'ReceivedCard': received_card,
            'Items': items,
        }
        location = self._location_payload()
        if location:
            payload['Location'] = location
        extra_info = self._extra_info(order=order, payment=payment)
        if extra_info:
            payload['ExtraInfo'] = extra_info
        return payload

    def _build_sale_items(self, *, order) -> list[dict]:
        items = []
        vat_percent = self._vat_percent(order=order)
        order_items = (
            order.items.exclude(status=OrderItem.Status.CANCELLED)
            .select_related('catalog_item', 'catalog_item__category')
            .order_by('created_at', 'id')
        )
        for item in order_items:
            item_payload = {
                'Name': str(getattr(item.catalog_item, 'name', '') or item.catalog_item.mxik_name or 'Item')[:128],
                'Amount': int(item.quantity or 0) * 1000,
                'Price': self._money_to_fiscal(item.line_total),
            }
            self._apply_vat(item_payload, amount=item.line_total, percent=vat_percent)
            spic = str(
                getattr(item.catalog_item, 'mxik_code', '')
                or getattr(getattr(item.catalog_item, 'category', None), 'mxik_code', '')
                or ''
            ).strip()
            if spic:
                item_payload['SPIC'] = spic
            barcode = self._extract_barcode(item=item)
            if barcode:
                item_payload['Barcode'] = barcode
            units = self._extract_units(item=item)
            if units is not None:
                item_payload['Units'] = units
            labels = self._extract_labels(item=item)
            if labels:
                item_payload['Labels'] = labels
            items.append(item_payload)

        service_fee = max(int(order.total or 0) - int(order.subtotal or 0), 0)
        if service_fee:
            service_payload = {'Name': 'Xizmat haqi', 'Amount': 1000, 'Price': self._money_to_fiscal(service_fee)}
            self._apply_vat(service_payload, amount=service_fee, percent=vat_percent)
            items.append(service_payload)

        if not items:
            raise FiscalDriveError('Order has no active items for fiscal receipt registration.')
        return items

    def _vat_percent(self, *, order) -> Decimal:
        if not bool(getattr(order.restaurant, 'vat_enabled', False)):
            return Decimal('0')
        try:
            percent = Decimal(str(getattr(order.restaurant, 'vat_percent', 0) or 0))
        except Exception:
            return Decimal('0')
        return max(percent, Decimal('0'))

    def _apply_vat(self, item_payload: dict, *, amount, percent: Decimal):
        if percent <= 0:
            return
        fiscal_amount = self._money_to_fiscal(amount)
        item_payload['VATPercent'] = int(percent.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        item_payload['VAT'] = int(
            (Decimal(fiscal_amount) * percent / (Decimal('100') + percent)).quantize(
                Decimal('1'),
                rounding=ROUND_HALF_UP,
            )
        )

    def _extract_units(self, *, item) -> int | None:
        for payload in [
            getattr(getattr(item, 'catalog_item', None), 'mxik_payload', None),
            getattr(getattr(getattr(item, 'catalog_item', None), 'category', None), 'mxik_payload', None),
        ]:
            value = self._find_first(
                payload,
                {
                    'unit_code',
                    'unitCode',
                    'common_unit_code',
                    'commonUnitCode',
                    'units',
                    'Units',
                    'unit',
                    'Unit',
                    'package_code',
                    'packageCode',
                    'package_code_id',
                    'packageCodeId',
                },
            )
            if value in (None, ''):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return self._default_unit_code()

    def _default_unit_code(self) -> int | None:
        value = self.settings.get('default_unit_code') or self.settings.get('defaultUnitCode') or 796
        try:
            unit_code = int(value)
        except (TypeError, ValueError):
            return None
        return unit_code if unit_code > 0 else None

    def _extract_barcode(self, *, item) -> str:
        for payload in [
            getattr(getattr(item, 'catalog_item', None), 'mxik_payload', None),
            getattr(getattr(getattr(item, 'catalog_item', None), 'category', None), 'mxik_payload', None),
        ]:
            value = self._find_first(
                payload,
                {'barcode', 'Barcode', 'bar_code', 'barCode', 'international_code', 'internationalCode', 'gtin', 'GTIN'},
            )
            barcode = ''.join(ch for ch in str(value or '') if ch.isdigit())
            if barcode:
                return barcode[:64]
        return ''

    def _extract_labels(self, *, item) -> list[str]:
        labels: list[str] = []
        for payload in [
            getattr(item, 'metadata', None),
            getattr(item, 'payload', None),
            getattr(item, 'extra', None),
            getattr(item, 'note', None),
        ]:
            value = self._find_first(
                payload,
                {'labels', 'Labels', 'marking_codes', 'markingCodes', 'marking_code', 'markingCode', 'label', 'Label'},
            )
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

    def _received_amounts(self, *, payment) -> tuple[int, int]:
        fiscal_cash = int(getattr(payment, 'fiscal_cash_amount', 0) or 0)
        fiscal_card = int(getattr(payment, 'fiscal_card_amount', 0) or 0)
        if fiscal_cash or fiscal_card:
            return self._money_to_fiscal(fiscal_cash), self._money_to_fiscal(fiscal_card)

        amount = self._money_to_fiscal(payment.amount)
        if payment.method == payment.Method.CASH:
            return amount, 0
        if payment.method in {payment.Method.CARD, payment.Method.QR}:
            return 0, amount
        if payment.method == payment.Method.MIXED:
            return self._money_to_fiscal(getattr(payment, 'cash_amount', 0)), self._money_to_fiscal(getattr(payment, 'card_amount', 0))
        raise FiscalDriveError(f"Payment method '{payment.method}' is not supported by the fiscal integration.")

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
        payload = {}
        tax_number = (
            self.settings.get('tax_number')
            or self.settings.get('taxNumber')
            or getattr(order.restaurant, 'tax_number', '')
        )
        if tax_number:
            payload['TIN'] = str(tax_number).strip()
        if payment.method == payment.Method.QR and payment.external_ref:
            payload['QRPaymentID'] = str(payment.external_ref).strip()
        return payload

    def _build_refund_info(self, response_payload: dict) -> dict:
        terminal_id = str(response_payload.get('TerminalID') or '').strip()
        receipt_seq = response_payload.get('ReceiptSeq')
        fiscal_sign = str(response_payload.get('FiscalSign') or '').strip()
        date_time = str(response_payload.get('DateTime') or '').strip()
        if not terminal_id or receipt_seq in (None, '') or not fiscal_sign or not date_time:
            raise FiscalDriveError('Original receipt payload is missing fields required for refund registration.')
        return {
            'TerminalID': terminal_id,
            'ReceiptSeq': int(receipt_seq),
            'DateTime': self._format_refund_datetime(date_time),
            'FiscalSign': fiscal_sign,
        }

