import ipaddress

from django.conf import settings
from django.http import HttpResponseNotFound


def _networks(setting_name: str):
    networks = []
    for value in getattr(settings, setting_name, []) or []:
        try:
            networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            # Configuration errors fail closed at request time; production
            # startup validation also rejects malformed values.
            return None
    return networks


def _address(value):
    try:
        return ipaddress.ip_address(str(value or '').strip())
    except ValueError:
        return None


def _in_networks(address, networks) -> bool:
    return address is not None and networks is not None and any(address in network for network in networks)


def admin_client_ip(request):
    remote = _address(request.META.get('REMOTE_ADDR'))
    trusted_proxies = _networks('DJANGO_ADMIN_TRUSTED_PROXY_CIDRS')
    if not _in_networks(remote, trusted_proxies):
        return remote

    forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
    current = remote
    for value in reversed(forwarded):
        if not _in_networks(current, trusted_proxies):
            break
        candidate = _address(value)
        if candidate is None:
            return None
        current = candidate
    return current


def django_admin_urlpatterns():
    if not getattr(settings, 'DJANGO_ADMIN_ENABLED', False):
        return []
    from django.contrib import admin
    from django.urls import path

    return [path('admin/', admin.site.urls)]


class DjangoAdminNetworkMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/admin' or request.path.startswith('/admin/'):
            if not getattr(settings, 'DJANGO_ADMIN_ENABLED', False):
                return HttpResponseNotFound()
            allowed = _networks('DJANGO_ADMIN_ALLOWED_CIDRS')
            if not allowed:
                if getattr(settings, 'DJANGO_PRODUCTION', False):
                    return HttpResponseNotFound()
            elif not _in_networks(admin_client_ip(request), allowed):
                return HttpResponseNotFound()
        return self.get_response(request)
