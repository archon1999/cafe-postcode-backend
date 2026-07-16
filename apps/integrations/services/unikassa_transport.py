from urllib.parse import urlparse

import httpx

from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError

from .unikassa_types import UnikassaFiscalError


class UnikassaTransportMixin:
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

