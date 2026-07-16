from __future__ import annotations

from types import SimpleNamespace

import httpx
from django.utils import timezone

from apps.billing.models import Receipt
from apps.local_agents.services import LocalAgentCommandService


from .unikassa_receipt_payload import UnikassaReceiptPayloadMixin
from .unikassa_transport import UnikassaTransportMixin
from .unikassa_types import FiscalReceiptPart, SUPPORTED_UNIKASSA_FISCAL_PROVIDERS, UnikassaFiscalError

__all__ = [
    'FiscalReceiptPart',
    'LocalAgentCommandService',
    'SUPPORTED_UNIKASSA_FISCAL_PROVIDERS',
    'UnikassaFiscalError',
    'UnikassaFiscalIntegrationService',
    'discover_unikassa_fiscal_devices',
]


class UnikassaFiscalIntegrationService(UnikassaTransportMixin, UnikassaReceiptPayloadMixin):
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
            'service_fee_percent': str(getattr(order.restaurant, 'service_fee_percent', 0) or 0),
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
