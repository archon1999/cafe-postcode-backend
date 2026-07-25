from rest_framework import generics, permissions
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.floor.models import ZoneOrCabin
from apps.floor.api.admin.serializers import ZoneOrCabinSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class ZoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            ZoneOrCabin.objects.select_related("restaurant"),
            self.request,
        )

    def perform_destroy(self, instance):
        if instance.halls.exists():
            raise serializers.ValidationError(
                {
                    "detail": _(
                        "This zone cannot be deleted while halls are assigned to it."
                    )
                }
            )
        instance.delete()
