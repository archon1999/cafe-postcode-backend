from rest_framework import generics, permissions
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.floor.models import ZoneOrCabin
from apps.floor.api.admin.serializers import ZoneOrCabinSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class ZoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return ZoneOrCabin.objects.filter(restaurant=restaurant)

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
