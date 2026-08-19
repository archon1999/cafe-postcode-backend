import ipaddress

from django.conf import settings


def _address(value):
    try:
        return ipaddress.ip_address(str(value or '').strip())
    except ValueError:
        return None


def _trusted_proxy_networks():
    networks = []
    for value in getattr(settings, 'CLIENT_IP_TRUSTED_PROXY_CIDRS', []) or []:
        try:
            networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            return []
    return networks


def _is_trusted(address, networks) -> bool:
    return address is not None and any(address in network for network in networks)


def get_client_ip(request) -> str | None:
    """Return a client IP without trusting forwarding headers from arbitrary peers."""
    remote = _address(request.META.get('REMOTE_ADDR'))
    trusted_proxies = _trusted_proxy_networks()
    if not _is_trusted(remote, trusted_proxies):
        return str(remote) if remote is not None else None

    cloudflare = _address(request.META.get('HTTP_CF_CONNECTING_IP'))
    if cloudflare is not None:
        return str(cloudflare)

    forwarded = [
        part.strip()
        for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')
        if part.strip()
    ]
    current = remote
    for value in reversed(forwarded):
        if not _is_trusted(current, trusted_proxies):
            break
        candidate = _address(value)
        if candidate is None:
            return str(remote) if remote is not None else None
        current = candidate
    return str(current) if current is not None else None
