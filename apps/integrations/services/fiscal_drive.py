from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import httpx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.billing.models import Receipt
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.sales.models import OrderItem


SUPPORTED_FISCAL_PROVIDERS = frozenset({'fiscal-drive-service'})


class FiscalDriveError(Exception):
    def __init__(self, message: str, *, code: str = ''):
        super().__init__(message)
        self.code = str(code or '')


@dataclass(slots=True)
class FiscalDriveTarget:
    factory_id: str
    info: dict


class FiscalDriveIntegrationService:
    default_endpoint_url = 'http://127.0.0.1:3449'

    def __init__(self, config, *, client_factory=httpx.Client):
        self.config = config
        self.settings = dict(getattr(config, 'settings', {}) or {})
        self.client_factory = client_factory

    def issue_receipt(self, *, order, payment):
        with self._client() as client:
            target = self._resolve_target(client=client, payment=payment)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            self._ensure_ready(target=target)
            receipt_payload = self._build_sale_receipt(order=order, payment=payment, memory_info=memory_info)
            return self._register_receipt(
                client=client,
                target=target,
                receipt_payload=receipt_payload,
                cashbox_id=self._cashbox_id(payment=payment),
                order=order,
            )

    def reprint_receipt(self, *, receipt):
        response_payload = dict(receipt.payload.get('response') or {})
        receipt_number = response_payload.get('ReceiptSeq') or receipt.payload.get('receipt_number')
        return {
            'ok': True,
            'provider': receipt.provider or self.config.provider,
            'receipt_number': str(receipt_number or ''),
            'reprinted_at': timezone.now().isoformat(),
            'response': response_payload,
            'qr_code_url': response_payload.get('QRCodeURL') or receipt.payload.get('qr_code_url'),
            'fiscal_sign': response_payload.get('FiscalSign') or receipt.payload.get('fiscal_sign'),
        }

    def issue_refund_receipt(self, *, order, payment, refund):
        original_receipt = (
            payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT)
            .order_by('-created_at')
            .first()
        )
        if original_receipt is None:
            raise FiscalDriveError('Original fiscal receipt was not found for the refund operation.')

        original_request = dict((original_receipt.payload or {}).get('request', {}) or {})
        original_response = dict((original_receipt.payload or {}).get('response', {}) or {})
        original_receipt_payload = dict(original_request.get('receipt') or {})
        if not original_receipt_payload:
            raise FiscalDriveError('Original fiscal receipt payload is missing and refund receipt cannot be composed.')

        refund_info = self._build_refund_info(original_response)
        refund_receipt_payload = {
            **original_receipt_payload,
            'Operation': 1,
            'RefundInfo': refund_info,
            'Time': self._format_operation_time(self._next_operation_datetime(None)),
        }

        with self._client() as client:
            target = self._resolve_target(client=client, payment=payment)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            self._ensure_ready(target=target)
            refund_receipt_payload['Time'] = self._format_operation_time(self._next_operation_datetime(memory_info))
            response = self._register_receipt(
                client=client,
                target=target,
                receipt_payload=refund_receipt_payload,
                cashbox_id=self._cashbox_id(payment=payment),
                order=order,
            )
            response['refund_id'] = str(refund.id)
            response['payment_id'] = str(payment.id)
            return response

    def open_shift(self, *, cash_desk=None):
        with self._client() as client:
            target = self._resolve_target(client=client, cash_desk=cash_desk)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            payload = None
            if self._should_open_z_report(client=client, factory_id=target.factory_id, memory_info=memory_info):
                payload = self._post_form(
                    client,
                    f'/FiscalDrive/ZReport/Open/{target.factory_id}',
                    {'DateTime': self._format_operation_time(self._next_operation_datetime(memory_info))},
                )
                memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            return {
                'ok': True,
                'provider': self.config.provider,
                'factory_id': target.factory_id,
                'terminal_id': str(target.info.get('TerminalID') or self._terminal_id(cash_desk=cash_desk)).strip(),
                'response': target.info,
                'provider_report': {
                    'open_result': payload if isinstance(payload, dict) else {'value': payload},
                    'fiscal_memory': memory_info if isinstance(memory_info, dict) else None,
                },
            }

    def close_shift(self, *, cash_desk=None):
        with self._client() as client:
            target = self._resolve_target(client=client, cash_desk=cash_desk)
            memory_info_before = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            z_info_before = self._get_last_z_report(
                client=client,
                factory_id=target.factory_id,
                memory_info=memory_info_before,
            )
            payload = self._post_form(
                client,
                f'/FiscalDrive/ZReport/Close/{target.factory_id}',
                {'DateTime': self._format_operation_time(self._next_operation_datetime(memory_info_before))},
            )
            z_sync_result = self._sync_z_reports(client=client, factory_id=target.factory_id)
            memory_info_after = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            z_info_after = self._get_last_z_report(
                client=client,
                factory_id=target.factory_id,
                memory_info=memory_info_after,
            )
        provider_report = {
            'z_info': z_info_after or z_info_before or {},
            'fiscal_memory': memory_info_after if isinstance(memory_info_after, dict) else None,
            'z_sync_result': z_sync_result,
        }
        return {
            'ok': True,
            'provider': self.config.provider,
            'factory_id': target.factory_id,
            'terminal_id': str((provider_report['z_info'] or {}).get('TerminalID') or target.info.get('TerminalID') or '').strip(),
            'response': payload if isinstance(payload, dict) else {'value': payload},
            'provider_report': provider_report,
        }

    def get_shift_report(self, *, cash_desk=None):
        with self._client() as client:
            target = self._resolve_target(client=client, cash_desk=cash_desk)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            report = self._get_last_z_report(
                client=client,
                factory_id=target.factory_id,
                memory_info=memory_info,
            ) or {}
        return {
            **report,
            'TerminalID': str(report.get('TerminalID') or target.info.get('TerminalID') or '').strip(),
            'FactoryID': target.factory_id,
            'SerialNumber': str(
                report.get('SerialNumber')
                or target.info.get('SerialNumber')
                or target.info.get('SN')
                or ''
            ).strip(),
        }

    def get_device_status(self, *, cash_desk=None):
        with self._client() as client:
            target = self._resolve_target(client=client, cash_desk=cash_desk)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
        return {
            'online': True,
            'provider': self.config.provider,
            'terminal_id': str(target.info.get('TerminalID') or self._terminal_id(cash_desk=cash_desk)).strip(),
            'detail': '',
            'response': {
                **target.info,
                'FactoryID': target.factory_id,
                'FiscalMemory': memory_info if isinstance(memory_info, dict) else None,
            },
        }

    def _client(self):
        return self.client_factory(base_url=self._endpoint_url(), timeout=self._timeout())

    def _endpoint_url(self) -> str:
        explicit = (
            self.settings.get('endpoint_url')
            or self.settings.get('endpointUrl')
            or self.settings.get('service_url')
            or self.settings.get('serviceUrl')
        )
        return str(explicit or self.default_endpoint_url).rstrip('/')

    def _timeout(self) -> float:
        try:
            return float(self.settings.get('timeout_seconds') or self.settings.get('timeoutSeconds') or 15)
        except (TypeError, ValueError):
            return 15.0

    def _post(self, client, path: str, *, data=None, json=None):
        if self._use_local_agent():
            return self._post_via_agent(path=path, data=data, json=json)

        try:
            response = client.post(path, data=data, json=json)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise FiscalDriveError(self._extract_error_message(error.response)) from error
        except httpx.RequestError as error:
            raise FiscalDriveError(f'FiscalDriveService request failed: {error}') from error

        text = response.text.strip()
        if not text:
            return None
        try:
            return response.json()
        except ValueError:
            return text

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text.strip()

        if isinstance(payload, dict):
            reason = payload.get('Reason') or payload.get('message') or payload.get('detail')
            if reason:
                return str(reason)
        if payload:
            return str(payload)
        return f'FiscalDriveService returned HTTP {response.status_code}.'

    def _use_local_agent(self) -> bool:
        return self.client_factory is httpx.Client

    def _restaurant(self):
        restaurant = getattr(self.config, 'restaurant', None)
        if restaurant is not None:
            return restaurant
        restaurant_id = getattr(self.config, 'restaurant_id', None)
        if restaurant_id is not None:
            from apps.restaurants.helpers import get_restaurant_model

            return get_restaurant_model().objects.get(pk=restaurant_id)
        return None

    def _post_via_agent(self, *, path: str, data=None, json=None):
        restaurant = self._restaurant()
        if restaurant is None:
            raise FiscalDriveError('Local agent fiscal request requires a restaurant-bound integration config.')
        try:
            result = LocalAgentCommandService().local_http_request(
                restaurant=restaurant,
                method='POST',
                url=f'{self._endpoint_url()}{path}',
                json_body=json,
                form_body=data,
                timeout_seconds=int(self._timeout()),
            )
        except LocalAgentUnavailableError as error:
            raise FiscalDriveError(str(error), code=error.code) from error
        except LocalAgentCommandError as error:
            raise FiscalDriveError(str(error), code=error.code) from error

        status_code = int(result.get('httpStatus') or 0)
        body = result.get('body')
        raw_body = str(result.get('rawBody') or '').strip()
        if status_code and not 200 <= status_code < 300:
            if isinstance(body, dict):
                reason = body.get('Reason') or body.get('message') or body.get('detail')
                raise FiscalDriveError(str(reason or body))
            raise FiscalDriveError(raw_body or f'FiscalDriveService returned HTTP {status_code}.')
        if body is not None:
            return body
        return raw_body or None

    def _post_form(self, client, path: str, data: dict | None = None):
        return self._post(client, path, data=data or {})

    def _post_json(self, client, path: str, payload):
        return self._post(client, path, json=payload)

    def _resolve_target(self, *, client, payment=None, cash_desk=None) -> FiscalDriveTarget:
        configured_factory_id = self._configured_factory_id()
        if configured_factory_id:
            info = self._get_fiscal_info(client=client, factory_id=configured_factory_id)
            return FiscalDriveTarget(factory_id=configured_factory_id, info=info)

        devices = self._list_fiscal_drives(client=client)
        if not devices:
            raise FiscalDriveError('No fiscal drives were detected by FiscalDriveService.')

        target_terminal_id = self._terminal_id(payment=payment, cash_desk=cash_desk)
        if target_terminal_id:
            for device in devices:
                factory_id = str(device.get('FactoryID') or '').strip()
                if not factory_id:
                    continue
                info = self._get_fiscal_info(client=client, factory_id=factory_id)
                if str(info.get('TerminalID') or '').strip() == target_terminal_id:
                    return FiscalDriveTarget(factory_id=factory_id, info=info)
            raise FiscalDriveError(f"Fiscal drive with terminal ID '{target_terminal_id}' was not found.")

        if len(devices) > 1:
            raise FiscalDriveError('Multiple fiscal drives detected; configure terminal_id or factory_id to select one.')

        factory_id = str(devices[0].get('FactoryID') or '').strip()
        if not factory_id:
            raise FiscalDriveError('FiscalDriveService returned a device without FactoryID.')
        info = self._get_fiscal_info(client=client, factory_id=factory_id)
        return FiscalDriveTarget(factory_id=factory_id, info=info)

    def _configured_factory_id(self) -> str:
        factory_id = self.settings.get('factory_id') or self.settings.get('factoryId')
        return str(factory_id or '').strip()

    def _terminal_id(self, *, payment=None, cash_desk=None) -> str:
        cash_desk = cash_desk or getattr(payment, 'cash_desk', None)
        if cash_desk is not None and getattr(cash_desk, 'terminal_id', ''):
            return str(cash_desk.terminal_id).strip()
        terminal_id = self.settings.get('terminal_id') or self.settings.get('terminalId')
        return str(terminal_id or '').strip()

    def _cashbox_id(self, *, payment) -> str:
        cash_desk = getattr(payment, 'cash_desk', None)
        if cash_desk is not None and getattr(cash_desk, 'external_cashbox_id', ''):
            return str(cash_desk.external_cashbox_id).strip()
        cashbox_id = self.settings.get('cashbox_id') or self.settings.get('cashboxId')
        return str(cashbox_id or '').strip()

    def _list_fiscal_drives(self, *, client) -> list[dict]:
        payload = self._post_form(client, '/FiscalDrive/List')
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get('value'), list):
            return payload['value']
        return []

    def _get_fiscal_info(self, *, client, factory_id: str) -> dict:
        payload = self._post_form(client, f'/FiscalDrive/Info/{factory_id}')
        if not isinstance(payload, dict):
            raise FiscalDriveError('FiscalDriveService returned an invalid fiscal drive info payload.')
        return payload

    def _get_fiscal_memory_info(self, *, client, factory_id: str) -> dict | None:
        try:
            payload = self._post_form(client, f'/FiscalDrive/FiscalMemory/Info/{factory_id}', {'Index': 0})
        except FiscalDriveError:
            return None
        return payload if isinstance(payload, dict) else None

    def _get_last_z_report(self, *, client, factory_id: str, memory_info: dict | None) -> dict | None:
        count = int((memory_info or {}).get('ZReportsCount') or 0)
        if count <= 0:
            return None
        payload = self._post_form(client, f'/FiscalDrive/ZReport/Info/{factory_id}', {'Index': count - 1})
        return payload if isinstance(payload, dict) else None

    def _ensure_ready(self, *, target: FiscalDriveTarget):
        if target.info.get('Locked'):
            raise FiscalDriveError('Fiscal drive is locked. Synchronize its state or unlock it from OFD first.')
        if target.info.get('POSLocked') and not target.info.get('POSAuth'):
            raise FiscalDriveError('Fiscal drive is POS-locked and requires POS authentication.')

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
                raise FiscalDriveError('Original fiscal receipt DateTime is invalid for refund registration.')
            return digits
        return timezone.localtime(parsed).strftime('%Y%m%d%H%M%S')

    def _should_open_z_report(self, *, client, factory_id: str, memory_info: dict | None) -> bool:
        if not self._auto_open_z_report():
            return False
        last_report = self._get_last_z_report(client=client, factory_id=factory_id, memory_info=memory_info)
        if last_report is None:
            return True
        return bool(last_report.get('CloseTime'))

    def _auto_open_z_report(self) -> bool:
        explicit = self.settings.get('auto_open_z_report')
        if explicit is None:
            explicit = self.settings.get('autoOpenZReport')
        if explicit is None:
            return True
        if isinstance(explicit, bool):
            return explicit
        return str(explicit).strip().lower() in {'1', 'true', 'yes', 'on'}

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

    def _register_receipt(self, *, client, target: FiscalDriveTarget, receipt_payload: dict, cashbox_id: str, order):
        try:
            return self._register_receipt_once(
                client=client,
                target=target,
                receipt_payload=receipt_payload,
                cashbox_id=cashbox_id,
                order=order,
            )
        except FiscalDriveError as error:
            if self._is_z_report_not_open_error(error):
                memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
                self._open_z_report(client=client, factory_id=target.factory_id, memory_info=memory_info)
                memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
                receipt_payload['Time'] = self._format_operation_time(self._next_operation_datetime(memory_info))
                return self._register_receipt_once(
                    client=client,
                    target=target,
                    receipt_payload=receipt_payload,
                    cashbox_id=cashbox_id,
                    order=order,
                )
            if not self._is_datetime_sync_error(error):
                raise
            self._sync_state(client=client, factory_id=target.factory_id)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            receipt_payload['Time'] = self._format_operation_time(self._next_operation_datetime(memory_info))
            return self._register_receipt_once(
                client=client,
                target=target,
                receipt_payload=receipt_payload,
                cashbox_id=cashbox_id,
                order=order,
            )

    def _register_receipt_once(self, *, client, target: FiscalDriveTarget, receipt_payload: dict, cashbox_id: str, order):
        memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
        if self._should_open_z_report(client=client, factory_id=target.factory_id, memory_info=memory_info):
            self._open_z_report(client=client, factory_id=target.factory_id, memory_info=memory_info)
            memory_info = self._get_fiscal_memory_info(client=client, factory_id=target.factory_id)
            receipt_payload['Time'] = self._format_operation_time(self._next_operation_datetime(memory_info))

        txid_payload = self._post_json(client, f'/FiscalDrive/Receipt/GetTXID/{target.factory_id}', receipt_payload)
        txid = self._extract_txid(txid_payload)
        response_payload = self._post_form(
            client,
            f'/FiscalDrive/Receipt/RegisterTXID/{target.factory_id}',
            {'TXID': txid},
        )
        sync_result = self._sync_full_receipts(client=client, factory_id=target.factory_id)
        receipt_number = response_payload.get('ReceiptSeq') if isinstance(response_payload, dict) else txid
        terminal_id = None
        if isinstance(response_payload, dict):
            terminal_id = response_payload.get('TerminalID')
        terminal_id = terminal_id or target.info.get('TerminalID')
        return {
            'ok': True,
            'provider': self.config.provider,
            'restaurant_name': order.restaurant.name,
            'restaurant_legal_name': order.restaurant.legal_name or order.restaurant.name,
            'restaurant_address': order.restaurant.address,
            'restaurant_phone': order.restaurant.phone,
            'restaurant_social': getattr(order.restaurant, 'social', ''),
            'service_fee_percent': str(getattr(order.restaurant, 'service_fee_percent', 0) or 0),
            'endpoint_url': self._endpoint_url(),
            'factory_id': target.factory_id,
            'terminal_id': terminal_id,
            'cashbox_id': cashbox_id or None,
            'receipt_number': str(receipt_number),
            'txid': txid,
            'fiscal_sign': response_payload.get('FiscalSign') if isinstance(response_payload, dict) else None,
            'qr_code_url': response_payload.get('QRCodeURL') if isinstance(response_payload, dict) else None,
            'issued_at': timezone.now().isoformat(),
            'response': response_payload if isinstance(response_payload, dict) else {'value': response_payload},
            'request': {'receipt': receipt_payload},
            'sync_result': sync_result,
        }

    @staticmethod
    def _extract_txid(payload) -> int:
        value = payload
        if isinstance(payload, dict):
            value = (
                payload.get('TXID')
                or payload.get('TxID')
                or payload.get('txid')
                or payload.get('txId')
                or payload.get('value')
            )
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise FiscalDriveError('FiscalDriveService returned an invalid receipt TXID.') from error

    def _sync_state(self, *, client, factory_id: str):
        self._post_form(client, f'/FiscalDrive/State/Sync/{factory_id}')

    def _open_z_report(self, *, client, factory_id: str, memory_info: dict | None):
        open_time = self._format_operation_time(self._next_operation_datetime(memory_info))
        return self._post_form(
            client,
            f'/FiscalDrive/ZReport/Open/{factory_id}',
            {'DateTime': open_time},
        )

    @staticmethod
    def _is_datetime_sync_error(error: FiscalDriveError) -> bool:
        detail = str(error).lower()
        return (
            'datetime_sync_with_server' in detail
            or '9091' in detail
            or 'receipt time is in the past' in detail
        )

    @staticmethod
    def _is_z_report_not_open_error(error: FiscalDriveError) -> bool:
        detail = str(error).lower()
        return 'zreport_is_not_opened' in detail or '9021' in detail

    def _sync_full_receipts(self, *, client, factory_id: str) -> dict:
        try:
            payload = self._post_form(client, f'/DataBase/Files/Sync/FullReceipts/{factory_id}', {'ItemsCount': 32})
        except FiscalDriveError as error:
            return {'ok': False, 'detail': str(error)}
        if isinstance(payload, dict):
            return {'ok': True, **payload}
        return {'ok': True, 'value': payload}

    def _sync_z_reports(self, *, client, factory_id: str) -> dict:
        try:
            payload = self._post_form(client, f'/DataBase/Files/Sync/ZReports/{factory_id}', {'ItemsCount': 32})
        except FiscalDriveError as error:
            return {'ok': False, 'detail': str(error)}
        if isinstance(payload, dict):
            return {'ok': True, **payload}
        return {'ok': True, 'value': payload}


def discover_fiscal_devices(
    *,
    restaurant=None,
    endpoint_url: str | None = None,
    timeout_seconds: float | None = None,
) -> list[dict]:
    settings = {}
    if endpoint_url:
        settings['endpoint_url'] = endpoint_url
    if timeout_seconds is not None:
        settings['timeout_seconds'] = timeout_seconds

    config = SimpleNamespace(provider='fiscal-drive-service', restaurant=restaurant, settings=settings)
    service = FiscalDriveIntegrationService(config)

    with service._client() as client:
        devices = service._list_fiscal_drives(client=client)
        discovered_devices = []
        for device in devices:
            factory_id = str(device.get('FactoryID') or '').strip()
            if not factory_id:
                continue
            info = service._get_fiscal_info(client=client, factory_id=factory_id)
            discovered_devices.append(
                {
                    'factory_id': factory_id,
                    'terminal_id': str(info.get('TerminalID') or '').strip(),
                    'reader_name': str(device.get('ReaderName') or '').strip(),
                    'description': str(device.get('Description') or '').strip(),
                    'applet_version': str(device.get('AppletVersion') or '').strip(),
                    'locked': bool(info.get('Locked')),
                    'pos_locked': bool(info.get('POSLocked')),
                    'pos_auth': bool(info.get('POSAuth')),
                    'endpoint_url': service._endpoint_url(),
                }
            )
        return discovered_devices
