from datetime import timedelta

import httpx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError

from .fiscal_drive_types import FiscalDriveError, FiscalDriveTarget


class FiscalDriveTransportMixin:
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
                purpose='fiscal-drive',
                integration_id=getattr(self.config, 'pk', None),
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
