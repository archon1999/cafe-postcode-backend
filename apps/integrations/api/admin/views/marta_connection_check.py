from urllib.parse import urlsplit, urlunsplit

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


def normalize_marta_endpoint(value: str) -> str:
    endpoint = str(value or '').strip().rstrip('/')
    if not endpoint:
        return ''
    if '://' not in endpoint:
        endpoint = f'http://{endpoint}'

    parsed = urlsplit(endpoint)
    if not parsed.hostname:
        return ''
    if parsed.port is None:
        host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        netloc = f'{host}:8090'
    else:
        netloc = parsed.netloc
    return urlunsplit((parsed.scheme or 'http', netloc, '', '', '')).rstrip('/')


class MartaConnectionCheckView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    command_service_class = LocalAgentCommandService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        raw_endpoint = request.data.get('endpointUrl') or request.data.get('endpoint_url') or ''
        try:
            endpoint_url = normalize_marta_endpoint(raw_endpoint)
        except ValueError:
            endpoint_url = ''
        if str(raw_endpoint).strip() and not endpoint_url:
            return Response(
                {'ok': False, 'code': 'MARTA_ADDRESS_INVALID', 'error': 'MARTA address is invalid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service = self.command_service_class()

        try:
            if endpoint_url:
                result = service.local_http_request(
                    restaurant=restaurant,
                    method='GET',
                    url=f'{endpoint_url}/health',
                    timeout_seconds=10,
                )
                health = result.get('body') if isinstance(result.get('body'), dict) else {}
                if result.get('ok') is not True or health.get('ok') is not True:
                    detail = str(health.get('message') or 'MARTA terminal is not ready.')
                    return Response(
                        {'ok': False, 'code': 'MARTA_NOT_READY', 'error': detail, 'result': result},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                return Response({'ok': True, 'endpointUrl': endpoint_url, 'health': health})

            result = service.execute(
                restaurant=restaurant,
                command_type='marta.discover',
                payload={'port': 8090, 'timeoutMillis': 900, 'maxConcurrency': 96},
                timeout_seconds=35,
            )
            devices = result.get('devices') if isinstance(result.get('devices'), list) else []
            device = devices[0] if devices and isinstance(devices[0], dict) else None
            if not device:
                return Response(
                    {'ok': False, 'code': 'MARTA_NOT_FOUND', 'error': 'MARTA terminal was not found.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            discovered_endpoint = str(device.get('endpointUrl') or device.get('endpoint_url') or '').rstrip('/')
            return Response({'ok': True, 'endpointUrl': discovered_endpoint, 'device': device})
        except LocalAgentUnavailableError as error:
            return Response(
                {'ok': False, 'error': str(error), 'code': error.code},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except LocalAgentCommandError as error:
            return Response(
                {'ok': False, 'error': str(error), 'code': error.code, 'result': error.result},
                status=status.HTTP_502_BAD_GATEWAY,
            )
