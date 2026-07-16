from __future__ import annotations

from types import SimpleNamespace

import httpx
from django.utils import timezone

from apps.billing.models import Receipt
from apps.local_agents.services import LocalAgentCommandService as LocalAgentCommandService

from .fiscal_drive_receipt_payload import FiscalDriveReceiptPayloadMixin
from .fiscal_drive_transport import FiscalDriveTransportMixin
from .fiscal_drive_types import FiscalDriveError, FiscalDriveTarget, SUPPORTED_FISCAL_PROVIDERS

__all__ = [
    'FiscalDriveError',
    'FiscalDriveIntegrationService',
    'FiscalDriveTarget',
    'LocalAgentCommandService',
    'SUPPORTED_FISCAL_PROVIDERS',
    'discover_fiscal_devices',
]


class FiscalDriveIntegrationService(FiscalDriveTransportMixin, FiscalDriveReceiptPayloadMixin):
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
