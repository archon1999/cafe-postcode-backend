from django.db import transaction

from apps.local_agents.invalidation import broadcast_operational_invalidation


class LocalAgentOperationalInvalidationMiddleware:
    """Notify the LAN Agent after successful direct POS state mutations."""

    mutation_methods = {'POST', 'PUT', 'PATCH', 'DELETE'}
    operational_prefixes = (
        '/api/v1/pos/sales/',
        '/api/v1/pos/billing/',
        '/api/v1/pos/floor/',
        '/api/v1/pos/kitchen/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not self._should_notify(request=request, response=response):
            return response

        restaurant = request.user.get_restaurant_scope()
        restaurant_id = restaurant.pk
        transaction.on_commit(
            lambda: broadcast_operational_invalidation(restaurant_id=restaurant_id)
        )
        return response

    def _should_notify(self, *, request, response):
        if request.method.upper() not in self.mutation_methods:
            return False
        if response.status_code < 200 or response.status_code >= 400:
            return False
        if not any(request.path.startswith(prefix) for prefix in self.operational_prefixes):
            return False
        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        get_scope = getattr(user, 'get_restaurant_scope', None)
        return callable(get_scope) and get_scope() is not None
