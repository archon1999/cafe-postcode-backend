import ipaddress
from urllib.parse import urlsplit


def private_lan_endpoints(values):
    endpoints = []
    for value in values[:8]:
        if not isinstance(value, str) or len(value) > 255:
            continue
        try:
            parsed = urlsplit(value)
            address = ipaddress.ip_address(parsed.hostname or '')
            port = parsed.port
        except (ValueError, TypeError):
            continue
        if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path not in ('', '/'):
            continue
        if address.version != 4 or not address.is_private or address.is_loopback or not port:
            continue
        endpoints.append(f'http://{address}:{port}')
    return endpoints
