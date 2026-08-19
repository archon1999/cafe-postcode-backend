import uuid

from rest_framework.throttling import SimpleRateThrottle
from rest_framework.throttling import UserRateThrottle

from common.api.client_ip import get_client_ip


class TrustedClientRateThrottle(SimpleRateThrottle):
    def get_trusted_ident(self, request):
        return get_client_ip(request) or 'unknown'


class LoginRateThrottle(TrustedClientRateThrottle):
    scope = 'login'

    def get_cache_key(self, request, view):
        ident = self.get_trusted_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class PinLoginRateThrottle(TrustedClientRateThrottle):
    scope = 'pin_login'

    def get_cache_key(self, request, view):
        ident = self.get_trusted_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class PinDeviceRateThrottle(SimpleRateThrottle):
    scope = 'pin_device'

    def get_cache_key(self, request, view):
        try:
            ident = str(uuid.UUID(str(request.headers.get('X-Device-Id', '')).strip()))
        except ValueError:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class DevicePairingRateThrottle(TrustedClientRateThrottle):
    scope = 'device_pairing'

    def get_cache_key(self, request, view):
        ident = self.get_trusted_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class DeviceMigrationRateThrottle(TrustedClientRateThrottle):
    scope = 'device_migration'

    def get_cache_key(self, request, view):
        ident = self.get_trusted_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class RestaurantCodeMigrationRateThrottle(TrustedClientRateThrottle):
    scope = 'restaurant_code_migration'

    def get_cache_key(self, request, view):
        ident = self.get_trusted_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class _ControlPairingUserRateThrottle(TrustedClientRateThrottle):
    def get_cache_key(self, request, view):
        user_id = getattr(getattr(request, 'user', None), 'pk', None) or 'anonymous'
        ident = f'{user_id}:{self.get_trusted_ident(request)}'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class ControlPairingResolveRateThrottle(_ControlPairingUserRateThrottle):
    scope = 'control_pairing_resolve'


class ControlPairingDecisionRateThrottle(_ControlPairingUserRateThrottle):
    scope = 'control_pairing_decision'
