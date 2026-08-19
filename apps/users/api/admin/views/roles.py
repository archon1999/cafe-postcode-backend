from rest_framework import generics

from apps.users.api.admin.serializers import RoleSerializer
from apps.users.api.admin.permissions import (
    PlatformPermissionRequiredMixin,
    RoleCollectionPermissionRequiredMixin,
)
from apps.users.selectors.users import RoleListFilters, prevent_system_role_delete, scoped_role_queryset


class RoleListCreateView(RoleCollectionPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        from apps.platform.selectors.business_partners import activation_role_queryset

        if self.request.user.get_business_partner_scope() is not None and not self.request.user.is_superuser:
            queryset = activation_role_queryset()
            return RoleListFilters.from_request(self.request).apply(queryset)
        queryset = scoped_role_queryset(self.request)
        return RoleListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(is_system=False)


class RoleRetrieveUpdateDestroyView(PlatformPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        return scoped_role_queryset(self.request)

    def perform_destroy(self, instance):
        prevent_system_role_delete(instance)
        instance.delete()

__all__ = ['RoleListCreateView', 'RoleRetrieveUpdateDestroyView']
