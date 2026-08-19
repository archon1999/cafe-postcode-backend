from rest_framework import generics

from apps.users.api.admin.serializers import PermissionOptionSerializer, PermissionSerializer
from apps.users.api.admin.permissions import (
    NonRestaurantPermissionRequiredMixin,
    PlatformPermissionRequiredMixin,
)
from apps.users.helpers import get_permission_model
from apps.users.selectors.users import PermissionListFilters

Permission = get_permission_model()


class PermissionListView(PlatformPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = PermissionSerializer

    def get_queryset(self):
        queryset = Permission.objects.prefetch_related('endpoints').all()
        return PermissionListFilters.from_request(self.request).apply(queryset)


class PermissionOptionsView(NonRestaurantPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = PermissionOptionSerializer
    pagination_class = None

    def get_queryset(self):
        from apps.platform.selectors.business_partners import activation_permission_queryset

        if self.request.user.get_business_partner_scope() is not None and not self.request.user.is_superuser:
            return activation_permission_queryset()
        return Permission.objects.order_by('code').all()

__all__ = ['PermissionListView', 'PermissionOptionsView']
