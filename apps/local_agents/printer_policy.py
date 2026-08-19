import base64
import binascii
import ipaddress
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from apps.integrations.models import IntegrationConfig


RAW_PRINTER_PORT = 9100
MAX_RAW_PAYLOAD_BYTES = 256 * 1024
MAX_RAW_PAYLOAD_ENCODED_BYTES = 4 * ((MAX_RAW_PAYLOAD_BYTES + 2) // 3)
MAX_PRINTER_TIMEOUT_SECONDS = 15


class PrinterPolicyError(Exception):
    def __init__(self, code: str):
        super().__init__('Printer command was denied by policy.')
        self.code = code


@dataclass(frozen=True)
class CanonicalPrinterTarget:
    integration_id: str
    connection_type: str
    printer_name: str
    host: str
    port: int | None


def _setting(settings: dict, *keys, default=None):
    for key in keys:
        value = settings.get(key)
        if value not in (None, ''):
            return value
    return default


def _normalize_host(value) -> str:
    return str(value or '').strip().rstrip('.').lower()


def _connection_type(value, host='') -> str:
    normalized = str(value or '').strip().lower()
    if not normalized:
        return 'socket' if _normalize_host(host) else 'system_printer'
    return normalized


def _configured_target(config: IntegrationConfig) -> CanonicalPrinterTarget:
    settings = dict(config.settings or {})
    host = _normalize_host(settings.get('host'))
    connection_type = _connection_type(
        _setting(settings, 'connection_type', 'connectionType', default=''),
        host,
    )
    printer_name = str(_setting(settings, 'printer_name', 'printerName', default='')).strip()
    if connection_type == 'socket':
        try:
            port = int(settings.get('port') or RAW_PRINTER_PORT)
        except (TypeError, ValueError) as error:
            raise PrinterPolicyError('configured_target_denied') from error
        if not host or port != RAW_PRINTER_PORT or _obviously_unsafe_host(host):
            raise PrinterPolicyError('configured_target_denied')
    elif connection_type == 'system_printer':
        host = ''
        port = None
        if printer_name and _unsafe_system_printer_name(printer_name):
            raise PrinterPolicyError('configured_target_denied')
    else:
        raise PrinterPolicyError('connection_type_denied')
    return CanonicalPrinterTarget(
        integration_id=str(config.id),
        connection_type=connection_type,
        printer_name=printer_name,
        host=host,
        port=port,
    )


def _obviously_unsafe_host(host: str) -> bool:
    if host in {
        'metadata',
        'metadata.google.internal',
        'instance-data',
        'instance-data.ec2.internal',
    } or host.endswith('.internal') or host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified


def _unsafe_system_printer_name(name: str) -> bool:
    return (
        len(name) > 255
        or any(character in name for character in ('\\', '/', ':'))
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
    )


def _matches(payload: dict, target: CanonicalPrinterTarget) -> bool:
    requested_id = str(payload.get('integrationId') or payload.get('integration_id') or '').strip()
    if requested_id and requested_id != target.integration_id:
        return False
    supplied_connection_type = payload.get('connectionType') or payload.get('connection_type')
    if supplied_connection_type and _connection_type(supplied_connection_type) != target.connection_type:
        return False
    if target.connection_type == 'socket':
        supplied_host = _normalize_host(payload.get('host'))
        if supplied_host and supplied_host != target.host:
            return False
        supplied_port = payload.get('port')
        if supplied_port not in (None, ''):
            try:
                if int(supplied_port) != target.port:
                    return False
            except (TypeError, ValueError):
                return False
        return bool(requested_id or supplied_host == target.host)
    supplied_name = str(payload.get('printerName') or payload.get('printer_name') or '').strip()
    if supplied_name and supplied_name.casefold() != target.printer_name.casefold():
        return False
    return bool(requested_id or (target.printer_name and supplied_name.casefold() == target.printer_name.casefold()))


def _candidate_configs(*, restaurant, integration_id: str):
    queryset = IntegrationConfig.objects.filter(
        restaurant=restaurant,
        kind=IntegrationConfig.Kind.PRINTER,
        is_enabled=True,
    ).order_by('id')
    if integration_id:
        try:
            queryset = queryset.filter(id=integration_id)
        except (TypeError, ValueError, ValidationError) as error:
            raise PrinterPolicyError('integration_denied') from error
    return queryset


def authorize_printer_command(*, restaurant, command_type: str, payload: dict) -> dict:
    if command_type not in {'printer.check', 'printer.raw'} or not isinstance(payload, dict):
        raise PrinterPolicyError('command_denied')
    integration_id = str(payload.get('integrationId') or payload.get('integration_id') or '').strip()
    matched = None
    configured_error = None
    for config in _candidate_configs(restaurant=restaurant, integration_id=integration_id):
        try:
            target = _configured_target(config)
        except PrinterPolicyError as error:
            configured_error = error
            if integration_id:
                raise
            continue
        if _matches(payload, target):
            matched = target
            break
    if matched is None:
        if configured_error is not None and integration_id:
            raise configured_error
        raise PrinterPolicyError('not_allowlisted')

    canonical = {
        'integrationId': matched.integration_id,
        'connectionType': matched.connection_type,
        'printerName': matched.printer_name,
        'host': matched.host,
        'port': matched.port,
    }
    if command_type == 'printer.raw':
        encoded = payload.get('payloadBase64')
        if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_RAW_PAYLOAD_ENCODED_BYTES:
            raise PrinterPolicyError('body_denied')
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise PrinterPolicyError('body_denied') from error
        if not decoded or len(decoded) > MAX_RAW_PAYLOAD_BYTES:
            raise PrinterPolicyError('body_denied')
        canonical['payloadBase64'] = encoded
        canonical['jobName'] = str(payload.get('jobName') or '')[:120]
    return canonical
