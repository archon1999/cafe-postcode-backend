from rest_framework import generics

from apps.platform.api.admin.serializers import TariffOptionSerializer, TariffSerializer
from apps.platform.api.admin.permissions import PlatformPermissionRequiredMixin
from apps.platform.helpers import get_tariff_model
from apps.platform.selectors.business_partners import filter_tariffs
from common.api.admin_permissions import AdminPermissionRequiredMixin

Tariff = get_tariff_model()


class TariffListCreateView(PlatformPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = TariffSerializer

    def get_queryset(self):
        return filter_tariffs(Tariff.objects.prefetch_related('permissions', 'allowed_roles'), self.request)


class TariffDetailView(PlatformPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = TariffSerializer

    def get_queryset(self):
        return Tariff.objects.prefetch_related('permissions', 'allowed_roles').order_by('name')


class TariffOptionsView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = TariffOptionSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Tariff.objects.filter(is_active=True).prefetch_related('permissions', 'allowed_roles')
        return filter_tariffs(queryset, self.request)

__all__ = ['TariffDetailView', 'TariffListCreateView', 'TariffOptionsView']
