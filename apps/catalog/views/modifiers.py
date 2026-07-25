from django.db.models import Count, Prefetch
from rest_framework import generics, permissions

from apps.catalog.models import ModifierGroup, ModifierOption
from apps.catalog.serializers import ModifierGroupSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant
from common.api.scopes import get_request_restaurant


class ModifierGroupListCreateView(generics.ListCreateAPIView):
    serializer_class = ModifierGroupSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = (
            ModifierGroup.objects.select_related("restaurant")
            .annotate(product_count=Count("item_assignments", distinct=True))
            .prefetch_related(
                Prefetch(
                    "options",
                    queryset=ModifierOption.objects.order_by("sort_order", "name"),
                )
            )
            .order_by("sort_order", "name")
        )
        return filter_queryset_by_optional_restaurant(queryset, self.request)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class ModifierGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ModifierGroupSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = (
            ModifierGroup.objects.select_related("restaurant")
            .annotate(product_count=Count("item_assignments", distinct=True))
            .prefetch_related(
                Prefetch(
                    "options",
                    queryset=ModifierOption.objects.order_by("sort_order", "name"),
                )
            )
        )
        return filter_queryset_by_optional_restaurant(queryset, self.request)

    def perform_destroy(self, instance):
        if instance.item_assignments.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])
            return
        instance.delete()
