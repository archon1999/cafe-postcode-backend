from common.api.permissions import EndpointRBACPermission


class IsOwnerDashboardUser(EndpointRBACPermission):
    """Backward-compatible alias for endpoint-based dashboard RBAC."""
