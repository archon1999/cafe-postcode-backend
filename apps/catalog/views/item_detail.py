from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework import generics, permissions

from apps.catalog.helpers import filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import EndpointRBACPermission


class ItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_catalog_queryset_by_scope(
            CatalogItem.objects.filter(archived_at__isnull=True), self.request
        ).select_related(
            'category__prep_station',
            'prep_station',
        ).prefetch_related('modifier_groups')

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            # Preserve historical order rows while removing this product from
            # all live catalog surfaces.
            if hasattr(instance, 'group_membership'):
                instance.group_membership.delete()
            instance.modifier_assignments.all().delete()
            instance.is_active = False
            instance.is_stoplisted = True
            instance.archived_at = timezone.now()
            instance.save(update_fields=('is_active', 'is_stoplisted', 'archived_at', 'updated_at'))
