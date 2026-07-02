from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.billing.models import Receipt
from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.sales.models import OrderItem


SUPPORTED_UNIKASSA_FISCAL_PROVIDERS = frozenset({'unikassa'})


class UnikassaFiscalError(Exception):
    def __init__(self, message: str, *, code: str = ''):
        super().__init__(message)
        self.code = str(code or '')


@dataclass(slots=True)
class FiscalReceiptPart:
    items: list[OrderItem]
    service_fee: int
    pay_type: str
    split_reason: str
    received_cash: int | None = None
    received_card: int | None = None


class UnikassaFiscalIntegrationService:
    default_endpoint_url = 'http://127.0.0.1:8181/api/v1'

    def __init__(self, config, *, client_factory=httpx.Client):
        self.config = config
        self.settings = dict(getattr(config, 'settings', {}) or {})
        self.client_factory = client_factory

    def issue_receipts(self, *, order, payment, split_reasons=None) -> list[dict]:
        parts = self._build_receipt_parts(order=order, payment=payment)
        if split_reasons:
            target_reasons = {str(reason or '') for reason in split_reasons}
            parts = [part for part in parts if part.split_reason in target_reasons]
            if not parts:
                raise UnikassaFiscalError('No fiscal receipt parts match the retry target.')
        responses = []
        with self._client() as client:
            memory_info = self._get_fiscal_memory_info(client=client, payment=payment)
            for part in parts:
                try:
                    receipt_payload = self._build_sale_receipt(
                        order=order,
                        payment=payment,
                        part=part,
                        memory_info=memory_info,
                    )
                    response = self._send_receipt(
                        client=client,
                        method='sale',
                        payment=payment,
                        pay_type=part.pay_type,
                        receipt_payload=receipt_payload,
                        split_reason=part.split_reason,
                        order=order,
                    )
                except Exception as error:
                    response = self._fiscal_failure_result(
                        error=error,
                        payment=payment,
                        pay_type=part.pay_type,
                        split_reason=part.split_reason,
                    )
                responses.append(response)
                if response.get('ok'):
                    memory_info = {'LastOperationTime': response.get('response', {}).get('DateTime')}
        return responses

    def issue_receipt(self, *, order, payment):
        responses = self.issue_receipts(order=order, payment=payment)
        return responses[0] if responses else {'ok': False, 'provider': self.config.provider, 'detail': 'No fiscal receipt parts.'}

    def issue_refund_receipt(self, *, order, payment, refund):
        original_receipt = (
            payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT)
            .order_by('-created_at')
            .first()
        )
        if original_receipt is None:
            raise UnikassaFiscalError('Original fiscal receipt was not found for the refund operation.')

        original_request = dict((original_receipt.payload or {}).get('request', {}) or {})
        original_response = dict((original_receipt.payload or {}).get('response', {}) or {})
        receipt_payload = dict(original_request.get('Receipt') or original_request.get('receipt') or {})
        if not receipt_payload:
            raise UnikassaFiscalError('Original fiscal receipt payload is missing and refund receipt cannot be composed.')

        receipt_payload['Operation'] = 1
        receipt_payload['RefundInfo'] = self._build_refund_info(original_response)

        with self._client() as client:
            memory_info = self._get_fiscal_memory_info(client=client, payment=payment)
            receipt_payload['Time'] = self._format_operation_time(self._next_operation_datetime(memory_info))
            result = self._send_receipt(
                client=client,
                method='refund',
                payment=payment,
                pay_type=str(original_request.get('PayType') or original_request.get('pay_type') or self._pay_type(payment)),
                receipt_payload=receipt_payload,
                split_reason='refund',
                order=order,
            )
            result['refund_id'] = str(refund.id)
            result['payment_id'] = str(payment.id)
            return result

    def reprint_receipt(self, *, receipt):
        response_payload = dict((receipt.payload or {}).get('response') or {})
        return {
            'ok': True,
            'provider': receipt.provider or self.config.provider,
            'receipt_number': str(response_payload.get('ReceiptSeq') or receipt.payload.get('receipt_number') or ''),
            'reprinted_at': timezone.now().isoformat(),
            'response': response_payload,
            'qr_code_url': response_payload.get('QRCodeURL') or receipt.payload.get('qr_code_url'),
            'fiscal_sign': response_payload.get('FiscalSign') or receipt.payload.get('fiscal_sign'),
        }

    def open_shift(self, *, cash_desk=None):
        with self._client() as client:
            payload = self._post_json_with_sync_retry(client, '/fiscal/open', {'Fiscal': self._fiscal(cash_desk=cash_desk)})
        return {'ok': True, 'provider': self.config.provider, 'response': payload}

    def close_shift(self, *, cash_desk=None):
        with self._client() as client:
            fiscal = self._fiscal(cash_desk=cash_desk)
            z_info = self._post_json_with_sync_retry(client, '/get/z-info', {'Fiscal': fiscal, 'Number': 0})
            payload = self._post_json_with_sync_retry(client, '/fiscal/close', {'Fiscal': fiscal})
            fiscal_memory = None
            fiscal_memory_error = ''
            try:
                fiscal_memory = self._post_json_with_sync_retry(client, '/get/fiscal-memory', {'Fiscal': fiscal, 'Number': None})
            except UnikassaFiscalError as error:
                fiscal_memory_error = str(error)
        provider_report = {
            'z_info': z_info if isinstance(z_info, dict) else {'value': z_info},
            'fiscal_memory': fiscal_memory if isinstance(fiscal_memory, dict) else None,
        }
        if fiscal_memory_error:
            provider_report['fiscal_memory_error'] = fiscal_memory_error
        return {
            'ok': True,
            'provider': self.config.provider,
            'response': payload,
            'provider_report': provider_report,
            'terminal_id': str((provider_report['z_info'] or {}).get('TerminalID') or fiscal),
        }

    def get_device_status(self, *, cash_desk=None):
        fiscal = self._fiscal(cash_desk=cash_desk)
        with self.client_factory(base_url=self._endpoint_url(), timeout=self._status_timeout()) as client:
            payload = self._post_json(client, '/get/info', {'Fiscal': fiscal, 'Number': None})
        payload = payload if isinstance(payload, dict) else {}
        return {
            'online': True,
            'provider': self.config.provider,
            'terminal_id': str(payload.get('TerminalID') or fiscal).strip(),
            'detail': '',
            'response': payload,
        }

    def _client(self):
        return self.client_factory(base_url=self._endpoint_url(), timeout=self._timeout())

    def _endpoint_url(self) -> str:
        return str(
            self.settings.get('endpoint_url')
            or self.settings.get('endpointUrl')
            or self.settings.get('service_url')
            or self.settings.get('serviceUrl')
            or self.default_endpoint_url
        ).rstrip('/')

    def _timeout(self) -> float:
        try:
            return float(self.settings.get('timeout_seconds') or self.settings.get('timeoutSeconds') or 15)
        except (TypeError, ValueError):
            return 15.0

    def _status_timeout(self) -> float:
        try:
            timeout = float(self.settings.get('status_timeout_seconds') or self.settings.get('statusTimeoutSeconds') or 3)
        except (TypeError, ValueError):
            timeout = 3.0
        return max(1.0, min(timeout, self._timeout()))

    def _post_json(self, client, path: str, payload: dict):
        if self._use_local_agent():
            return self._post_json_via_agent(path=path, payload=payload)

        try:
            response = client.post(path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise self._error_from_response(error.response) from error
        except httpx.RequestError as error:
            raise UnikassaFiscalError(f'Unikassa request failed: {error}') from error

        text = response.text.strip()
        if not text:
            return None
        try:
            payload = response.json()
        except ValueError:
            return text
        if isinstance(payload, dict) and payload.get('error'):
            error = payload['error'] if isinstance(payload['error'], dict) else {}
            raise UnikassaFiscalError(str(error.get('message') or payload['error']), code=str(error.get('code') or ''))
        return payload

    def _error_from_response(self, response: httpx.Response) -> UnikassaFiscalError:
        try:
            payload = response.json()
        except ValueError:
            return UnikassaFiscalError(response.text.strip() or f'Unikassa returned HTTP {response.status_code}.')
        if isinstance(payload, dict) and isinstance(payload.get('error'), dict):
            error = payload['error']
            return UnikassaFiscalError(str(error.get('message') or payload), code=str(error.get('code') or ''))
        if isinstance(payload, dict):
            return UnikassaFiscalError(str(payload.get('message') or payload.get('detail') or payload))
        return UnikassaFiscalError(str(payload))

    def _use_local_agent(self) -> bool:
        return self.client_factory is httpx.Client

    def _post_json_via_agent(self, *, path: str, payload: dict):
        restaurant = getattr(self.config, 'restaurant', None)
        if restaurant is None:
            restaurant_id = getattr(self.config, 'restaurant_id', None)
            if restaurant_id is not None:
                from apps.restaurants.helpers import get_restaurant_model

                restaurant = get_restaurant_model().objects.get(pk=restaurant_id)
        if restaurant is None:
            raise UnikassaFiscalError('Local agent fiscal request requires a restaurant-bound integration config.')

        endpoint_url = self._configured_endpoint_url()
        if not endpoint_url:
            discovered_url = self._discover_endpoint_url(
                restaurant=restaurant,
                fiscal=str(payload.get('Fiscal') or ''),
                reason='missing_endpoint',
            )
            if discovered_url:
                endpoint_url = discovered_url
            else:
                raise UnikassaFiscalError(
                    'Unikassa terminal was not found on the local network.',
                    code='UNIKASSA_NOT_FOUND',
                )

        try:
            return self._post_json_via_agent_endpoint(
                restaurant=restaurant,
                endpoint_url=endpoint_url,
                path=path,
                payload=payload,
            )
        except UnikassaFiscalError as error:
            if not self._should_rediscover_after_agent_error(error):
                raise
            discovered_url = self._discover_endpoint_url(
                restaurant=restaurant,
                fiscal=str(payload.get('Fiscal') or ''),
                reason=str(getattr(error, 'code', '') or 'request_failed'),
            )
            if not discovered_url or discovered_url == endpoint_url:
                raise
            return self._post_json_via_agent_endpoint(
                restaurant=restaurant,
                endpoint_url=discovered_url,
                path=path,
                payload=payload,
            )

    def _post_json_via_agent_endpoint(self, *, restaurant, endpoint_url: str, path: str, payload: dict):
        try:
            result = LocalAgentCommandService().local_http_request(
                restaurant=restaurant,
                method='POST',
                url=f'{endpoint_url}{path}',
                json_body=payload,
                timeout_seconds=int(self._timeout()),
            )
        except LocalAgentUnavailableError as error:
            raise UnikassaFiscalError(str(error), code=error.code) from error
        except LocalAgentCommandError as error:
            raise UnikassaFiscalError(str(error), code=error.code) from error

        status_code = int(result.get('httpStatus') or 0)
        body = result.get('body') if isinstance(result.get('body'), dict) else None
        raw_body = str(result.get('rawBody') or '').strip()
        if status_code and not 200 <= status_code < 300:
            if body:
                if isinstance(body.get('error'), dict):
                    error = body['error']
                    raise UnikassaFiscalError(str(error.get('message') or body), code=str(error.get('code') or ''))
                raise UnikassaFiscalError(str(body.get('message') or body.get('detail') or body))
            raise UnikassaFiscalError(raw_body or f'Unikassa returned HTTP {status_code}.')
        if body is not None:
            if body.get('error'):
                error = body['error'] if isinstance(body['error'], dict) else {}
                raise UnikassaFiscalError(str(error.get('message') or body['error']), code=str(error.get('code') or ''))
            return body
        return raw_body or None

    def _configured_endpoint_url(self) -> str:
        explicit = (
            self.settings.get('endpoint_url')
            or self.settings.get('endpointUrl')
            or self.settings.get('service_url')
            or self.settings.get('serviceUrl')
        )
        return str(explicit or '').rstrip('/')

    def _discover_endpoint_url(self, *, restaurant, fiscal: str, reason: str) -> str:
        try:
            result = LocalAgentCommandService().execute(
                restaurant=restaurant,
                command_type='unikassa.discover',
                payload={
                    'port': self._positive_int('discovery_port', 'discoveryPort', fallback=8181),
                    'pathPrefix': self._path_prefix(),
                    'fiscal': fiscal,
                    'timeoutMillis': self._positive_int(
                        'discovery_timeout_millis',
                        'discoveryTimeoutMillis',
                        fallback=900,
                    ),
                    'maxConcurrency': self._positive_int(
                        'discovery_max_concurrency',
                        'discoveryMaxConcurrency',
                        fallback=96,
                    ),
                    'reason': reason,
                },
                timeout_seconds=35,
            )
        except LocalAgentUnavailableError as error:
            raise UnikassaFiscalError(str(error), code=error.code) from error
        except LocalAgentCommandError as error:
            raise UnikassaFiscalError(str(error), code=error.code) from error
        devices = result.get('devices') if isinstance(result.get('devices'), list) else []
        first_device = devices[0] if devices and isinstance(devices[0], dict) else {}
        endpoint_url = str(first_device.get('endpointUrl') or first_device.get('endpoint_url') or '').rstrip('/')
        if endpoint_url:
            self._persist_endpoint_url(endpoint_url)
        return endpoint_url

    def _path_prefix(self) -> str:
        configured = self._configured_endpoint_url()
        parsed = urlparse(configured or self.default_endpoint_url)
        path = str(parsed.path or '').rstrip('/')
        return path or '/api/v1'

    def _persist_endpoint_url(self, endpoint_url: str):
        self.settings['endpoint_url'] = endpoint_url
        self.config.settings = self.settings
        if not hasattr(self.config, 'save'):
            return
        try:
            self.config.save(update_fields=['settings', 'updated_at'])
        except Exception:
            return

    def _positive_int(self, *keys: str, fallback: int) -> int:
        for key in keys:
            value = self.settings.get(key)
            if value in (None, ''):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return fallback

    @staticmethod
    def _should_rediscover_after_agent_error(error: UnikassaFiscalError) -> bool:
        code = str(getattr(error, 'code', '') or '')
        return code in {'AGENT_COMMAND_ERROR', 'LOCAL_AGENT_ERROR', 'LOCAL_AGENT_TIMEOUT'}

    def _post_json_with_sync_retry(self, client, path: str, payload: dict):
        try:
            return self._post_json(client, path, payload)
        except UnikassaFiscalError as error:
            if not self._is_datetime_sync_error(error):
                raise
            fiscal = str(payload.get('Fiscal') or '').strip()
            if not fiscal:
                raise
            try:
                self._post_json(client, '/get/sync', {'Fiscal': fiscal, 'Number': None})
            except UnikassaFiscalError:
                raise error
            return self._post_json(client, path, payload)

    @staticmethod
    def _is_datetime_sync_error(error: Exception) -> bool:
        code = str(getattr(error, 'code', '') or '')
        detail = str(error)
        return code == '9091' or 'DATETIME_SYNC_WITH_SERVER' in detail

    def _fiscal(self, *, cash_desk=None) -> str:
        if cash_desk is not None and getattr(cash_desk, 'terminal_id', ''):
            return str(cash_desk.terminal_id).strip()
        fiscal = self.settings.get('fiscal') or self.settings.get('Fiscal') or self.settings.get('terminal_id') or self.settings.get('terminalId')
        fiscal = str(fiscal or '').strip()
        if not fiscal:
            raise UnikassaFiscalError('Fiscal terminal is not configured.')
        return fiscal

    def _get_fiscal_memory_info(self, *, client, payment) -> dict | None:
        try:
            payload = self._post_json(
                client,
                '/get/fiscal-memory',
                {'Fiscal': self._fiscal(cash_desk=getattr(payment, 'cash_desk', None)), 'Number': None},
            )
        except UnikassaFiscalError:
            return None
        return payload if isinstance(payload, dict) else None

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

    def _send_receipt(self, *, client, method: str, payment, pay_type: str, receipt_payload: dict, split_reason: str, order):
        requested_at = timezone.now()
        request_payload = {
            'Fiscal': self._fiscal(cash_desk=getattr(payment, 'cash_desk', None)),
            'PayType': pay_type,
            'Receipt': receipt_payload,
        }
        response_payload = self._post_json_with_sync_retry(client, f'/send/{method}', request_payload)
        response_payload = response_payload if isinstance(response_payload, dict) else {'value': response_payload}
        return {
            'ok': True,
            'provider': self.config.provider,
            'restaurant_name': order.restaurant.name,
            'restaurant_legal_name': order.restaurant.legal_name or order.restaurant.name,
            'restaurant_address': order.restaurant.address,
            'restaurant_phone': order.restaurant.phone,
            'restaurant_social': getattr(order.restaurant, 'social', ''),
            'tax_number': order.restaurant.tax_number,
            'endpoint_url': self._endpoint_url(),
            'terminal_id': response_payload.get('TerminalID') or request_payload['Fiscal'],
            'receipt_number': str(response_payload.get('ReceiptSeq') or ''),
            'fiscal_sign': response_payload.get('FiscalSign'),
            'qr_code_url': response_payload.get('QRCodeURL'),
            'issued_at': timezone.now().isoformat(),
            'fiscal_requested_at': requested_at.isoformat(),
            'fiscal_registered_at': self._parse_registered_datetime(response_payload.get('DateTime')),
            'original_paid_at': payment.paid_at.isoformat() if payment.paid_at else None,
            'fiscal_pay_type': pay_type,
            'split_reason': split_reason,
            'response': response_payload,
            'request': request_payload,
        }

    def _fiscal_failure_result(self, *, error, payment, pay_type: str, split_reason: str):
        requested_at = timezone.now()
        return {
            'ok': False,
            'provider': self.config.provider,
            'code': str(getattr(error, 'code', '') or ''),
            'detail': str(error),
            'issued_at': requested_at.isoformat(),
            'fiscal_requested_at': requested_at.isoformat(),
            'original_paid_at': payment.paid_at.isoformat() if payment.paid_at else None,
            'fiscal_pay_type': pay_type,
            'split_reason': split_reason,
        }

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


def discover_unikassa_fiscal_devices(*, endpoint_url: str | None = None, timeout_seconds: float | None = None) -> list[dict]:
    settings = {}
    if endpoint_url:
        settings['endpoint_url'] = endpoint_url
    if timeout_seconds is not None:
        settings['timeout_seconds'] = timeout_seconds
    config = SimpleNamespace(provider='unikassa', settings=settings)
    service = UnikassaFiscalIntegrationService(config)
    with service._client() as client:
        fiscal = service._fiscal()
        info = service._post_json(client, '/get/info', {'Fiscal': fiscal, 'Number': None})
        return [{'factory_id': fiscal, 'terminal_id': str((info or {}).get('TerminalID') or fiscal), 'endpoint_url': service._endpoint_url()}]
