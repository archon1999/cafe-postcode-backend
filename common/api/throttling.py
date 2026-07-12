from rest_framework.throttling import SimpleRateThrottle
from rest_framework.throttling import UserRateThrottle


class LoginRateThrottle(SimpleRateThrottle):
    scope = 'login'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class PinLoginRateThrottle(SimpleRateThrottle):
    scope = 'pin_login'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class AgentEnrollmentRateThrottle(SimpleRateThrottle):
    scope = 'agent_enrollment'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}
