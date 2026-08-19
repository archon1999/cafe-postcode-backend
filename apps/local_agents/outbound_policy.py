import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from apps.integrations.models import IntegrationConfig


class OutboundPolicyError(ValueError):
    def __init__(self, message: str, *, code: str = 'policy_denied'):
        super().__init__(message)
        self.code = code


PURPOSE_MARTA = 'marta'
PURPOSE_FISCAL_DRIVE = 'fiscal-drive'
PURPOSE_UNIKASSA = 'unikassa'

MAX_LOCAL_HTTP_BODY_BYTES = 128 * 1024
MAX_LOCAL_HTTP_TIMEOUT_SECONDS = 30

_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*'
    r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$',
    re.IGNORECASE,
)
_METADATA_HOSTS = frozenset(
    {
        '169.254.169.254',
        'metadata',
        'metadata.google.internal',
        'instance-data',
        'instance-data.ec2.internal',
    }
)


@dataclass(frozen=True)
class PurposeRule:
    kind: str
    providers: frozenset[str]
    port: int
    methods: frozenset[str]
    exact_paths: frozenset[str] = frozenset()
    path_prefixes: tuple[str, ...] = ()
    allow_loopback: bool = False
    default_endpoint: str = ''
    allowed_query_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AuthorizedOutboundRequest:
    purpose: str
    integration_id: str
    url: str
    timeout_seconds: int


PURPOSE_RULES = {
    PURPOSE_MARTA: PurposeRule(
        kind=IntegrationConfig.Kind.PAYMENT,
        providers=frozenset({'marta-softpos'}),
        port=8090,
        methods=frozenset({'GET'}),
        exact_paths=frozenset({'/health', '/transaction'}),
        allowed_query_keys=frozenset({'type', 'amount', 'pid', 'tin'}),
    ),
    PURPOSE_FISCAL_DRIVE: PurposeRule(
        kind=IntegrationConfig.Kind.FISCAL,
        providers=frozenset({'fiscal-drive-service'}),
        port=3449,
        methods=frozenset({'POST'}),
        path_prefixes=('/FiscalDrive/', '/DataBase/Files/Sync/'),
        # FiscalDriveService is commonly installed on the same Windows till.
        # This is the only narrow loopback exception: fixed provider, port,
        # method, path and restaurant integration.
        allow_loopback=True,
        default_endpoint='http://127.0.0.1:3449',
    ),
    PURPOSE_UNIKASSA: PurposeRule(
        kind=IntegrationConfig.Kind.FISCAL,
        providers=frozenset({'unikassa'}),
        port=8181,
        methods=frozenset({'POST'}),
        path_prefixes=('/get/', '/receipt/', '/shift/', '/system/'),
        allow_loopback=True,
        default_endpoint='http://127.0.0.1:8181/api/v1',
    ),
}


def _settings_endpoint(config: IntegrationConfig, rule: PurposeRule) -> str:
    values = dict(config.settings or {})
    endpoint = (
        values.get('endpoint_url')
        or values.get('endpointUrl')
        or values.get('service_url')
        or values.get('serviceUrl')
        or rule.default_endpoint
    )
    return str(endpoint or '').strip().rstrip('/')


def _parse_url(value: str, *, rule: PurposeRule):
    raw = str(value or '').strip()
    if not raw or len(raw) > 2048:
        raise OutboundPolicyError('Local integration URL is missing or too long.', code='invalid_url')
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise OutboundPolicyError('Local integration URL is invalid.', code='invalid_url') from error
    if parsed.scheme.lower() != 'http':
        raise OutboundPolicyError(
            'Only plain HTTP is supported for isolated LAN integrations.',
            code='scheme_denied',
        )
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise OutboundPolicyError(
            'Credentials and fragments are forbidden in local integration URLs.',
            code='credentials_or_fragment',
        )
    if not parsed.hostname or port != rule.port:
        raise OutboundPolicyError(f'Local integration must use TCP port {rule.port}.', code='port_denied')

    host = parsed.hostname.rstrip('.').lower()
    if host in _METADATA_HOSTS:
        raise OutboundPolicyError('Cloud metadata targets are forbidden.', code='metadata_denied')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '%' in host or not _HOSTNAME_RE.fullmatch(host):
            raise OutboundPolicyError('Local integration hostname is invalid.', code='invalid_host')
        if host == 'localhost' or host.endswith('.localhost'):
            if not rule.allow_loopback:
                raise OutboundPolicyError(
                    'Loopback targets are forbidden for this integration.',
                    code='loopback_denied',
                )
        elif host.endswith('.internal'):
            raise OutboundPolicyError(
                'Internal metadata-style hostnames are forbidden.',
                code='metadata_denied',
            )
    else:
        if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved:
            raise OutboundPolicyError('Unsafe IP address class is forbidden.', code='address_class_denied')
        if address.is_loopback:
            if not rule.allow_loopback:
                raise OutboundPolicyError(
                    'Loopback targets are forbidden for this integration.',
                    code='loopback_denied',
                )
        elif not address.is_private:
            raise OutboundPolicyError(
                'Local integration target must use a private LAN address.',
                code='public_address_denied',
            )
    return parsed


def _origin(parsed) -> tuple[str, str, int]:
    return parsed.scheme.lower(), parsed.hostname.rstrip('.').lower(), parsed.port


def _relative_path(target, base) -> str:
    base_path = (base.path or '').rstrip('/')
    target_path = target.path or '/'
    if base_path:
        if target_path == base_path:
            return '/'
        prefix = base_path + '/'
        if not target_path.startswith(prefix):
            raise OutboundPolicyError(
                'Request path escapes the configured integration endpoint.',
                code='path_escape',
            )
        return '/' + target_path[len(prefix) :]
    return target_path


def _validate_path(path: str, rule: PurposeRule) -> None:
    try:
        decoded_path = unquote(path, errors='strict')
    except (UnicodeDecodeError, ValueError) as error:
        raise OutboundPolicyError('Local integration path is not canonical.', code='invalid_path') from error
    if (
        '%' in path
        or '\\' in path
        or '\\' in decoded_path
        or '\x00' in decoded_path
        or '/../' in f'{decoded_path}/'
        or '/./' in f'{decoded_path}/'
        or decoded_path.startswith('//')
    ):
        raise OutboundPolicyError('Local integration path is not canonical.', code='invalid_path')
    if path in rule.exact_paths:
        return
    if any(path.startswith(prefix) for prefix in rule.path_prefixes):
        return
    raise OutboundPolicyError('Path is not allowed for this integration purpose.', code='path_denied')


def _validate_query(query: str, rule: PurposeRule) -> None:
    if not query:
        return
    if not rule.allowed_query_keys or len(query.encode('utf-8')) > 2048:
        raise OutboundPolicyError('Query parameters are not allowed for this purpose.', code='query_denied')
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
    except (ValueError, UnicodeDecodeError) as error:
        raise OutboundPolicyError('Local integration query is invalid.', code='invalid_query') from error
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)) or any(key not in rule.allowed_query_keys for key in keys):
        raise OutboundPolicyError('Query parameters are not allowed for this purpose.', code='query_denied')
    if any(len(value.encode('utf-8')) > 256 for _key, value in pairs):
        raise OutboundPolicyError('Local integration query value is too long.', code='query_denied')


def _encoded_body_size(*, json_body, form_body) -> int:
    try:
        if json_body is not None:
            # Deliberately retain default separators so this is conservative
            # even if the channel serializer includes whitespace. The agent
            # applies the same limit to the exact JSON bytes it receives.
            return len(json.dumps(json_body, ensure_ascii=False).encode('utf-8'))
        if form_body is not None:
            values = {
                str(key): '' if value is None else str(value)
                for key, value in dict(form_body).items()
                if str(key)
            }
            return len(urlencode(values).encode('utf-8'))
    except (TypeError, ValueError, OverflowError) as error:
        raise OutboundPolicyError(
            'Local integration request body is not serializable.',
            code='invalid_body',
        ) from error
    return 0


def authorize_local_http_request(
    *,
    restaurant,
    purpose: str,
    method: str,
    url: str,
    timeout_seconds: int,
    integration_id=None,
    json_body=None,
    form_body=None,
) -> AuthorizedOutboundRequest:
    normalized_purpose = str(purpose or '').strip().lower()
    rule = PURPOSE_RULES.get(normalized_purpose)
    if rule is None:
        raise OutboundPolicyError(
            'A supported local integration purpose is required.',
            code='purpose_denied',
        )
    normalized_method = str(method or '').strip().upper()
    if normalized_method not in rule.methods:
        raise OutboundPolicyError(
            'HTTP method is not allowed for this integration purpose.',
            code='method_denied',
        )
    try:
        bounded_timeout = int(timeout_seconds or 0)
    except (TypeError, ValueError) as error:
        raise OutboundPolicyError('Local integration timeout is invalid.', code='invalid_timeout') from error
    if not 1 <= bounded_timeout <= MAX_LOCAL_HTTP_TIMEOUT_SECONDS:
        raise OutboundPolicyError(
            f'Local integration timeout must be between 1 and {MAX_LOCAL_HTTP_TIMEOUT_SECONDS} seconds.'
        )
    if _encoded_body_size(json_body=json_body, form_body=form_body) > MAX_LOCAL_HTTP_BODY_BYTES:
        raise OutboundPolicyError(
            'Local integration request body exceeds 128 KiB.',
            code='body_too_large',
        )

    target = _parse_url(url, rule=rule)
    candidates = IntegrationConfig.objects.filter(
        restaurant=restaurant,
        is_enabled=True,
        kind=rule.kind,
        provider__in=rule.providers,
    )
    if integration_id:
        candidates = candidates.filter(pk=integration_id)
    for config in candidates:
        endpoint = _settings_endpoint(config, rule)
        if not endpoint:
            continue
        try:
            base = _parse_url(endpoint, rule=rule)
        except OutboundPolicyError:
            continue
        if base.query or base.fragment or _origin(target) != _origin(base):
            continue
        try:
            relative_path = _relative_path(target, base)
            _validate_path(relative_path, rule)
            _validate_query(target.query, rule)
        except OutboundPolicyError:
            continue
        normalized_url = urlunsplit(
            (target.scheme.lower(), target.netloc, target.path or '/', target.query, '')
        )
        return AuthorizedOutboundRequest(
            purpose=normalized_purpose,
            integration_id=str(config.pk),
            url=normalized_url,
            timeout_seconds=bounded_timeout,
        )
    raise OutboundPolicyError(
        'Target is not allowlisted by an enabled integration for this restaurant.',
        code='not_allowlisted',
    )


def normalize_discovery_payload(command_type: str, payload: dict) -> dict:
    values = dict(payload or {})
    if command_type == 'marta.discover':
        expected_port = 8090
        allowed_keys = {'port', 'timeoutMillis', 'maxConcurrency', 'reason'}
    elif command_type == 'unikassa.discover':
        expected_port = 8181
        allowed_keys = {'port', 'pathPrefix', 'fiscal', 'timeoutMillis', 'maxConcurrency', 'reason'}
        path_prefix = '/' + str(values.get('pathPrefix') or '/api/v1').strip().strip('/')
        if path_prefix != '/api/v1':
            raise OutboundPolicyError('Unikassa discovery path must be /api/v1.', code='discovery_path_denied')
        values['pathPrefix'] = path_prefix
    else:
        return values
    if set(values) - allowed_keys:
        raise OutboundPolicyError('Discovery payload contains unsupported fields.', code='discovery_fields_denied')
    try:
        port = int(values.get('port') or expected_port)
        timeout_millis = int(values.get('timeoutMillis') or 900)
        concurrency = int(values.get('maxConcurrency') or 96)
    except (TypeError, ValueError) as error:
        raise OutboundPolicyError('Discovery limits are invalid.', code='invalid_discovery_limits') from error
    if port != expected_port:
        raise OutboundPolicyError(
            f'Discovery is restricted to TCP port {expected_port}.',
            code='discovery_port_denied',
        )
    if not 100 <= timeout_millis <= 2000 or not 1 <= concurrency <= 128:
        raise OutboundPolicyError(
            'Discovery timeout or concurrency exceeds the safety limit.',
            code='discovery_limits_denied',
        )
    values['port'] = port
    values['timeoutMillis'] = timeout_millis
    values['maxConcurrency'] = concurrency
    return values
