from django.shortcuts import get_object_or_404
from rest_framework import generics, response, views

from apps.floor.api.admin.serializers import (
    HallConstructorSerializer,
    HallConstructorUpdateSerializer,
)
from apps.floor.selectors.floor import hall_constructor_queryset
from apps.floor.services import HallConstructorService
from common.api.admin_permissions import AdminPermissionRequiredMixin


class HallConstructorView(AdminPermissionRequiredMixin, views.APIView):
    constructor_service_class = HallConstructorService

    def get_queryset(self):
        return hall_constructor_queryset(self.request)

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get(self, request, pk):
        hall = self.get_object(pk)
        serializer = HallConstructorSerializer(hall)
        return response.Response(serializer.data)

    def put(self, request, pk):
        hall = self.get_object(pk)
        serializer = HallConstructorUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        hall = self.constructor_service_class().save_layout(
            hall=hall,
            grid_columns=serializer.validated_data['grid_columns'],
            service_fee_enabled=serializer.validated_data['service_fee_enabled'],
            service_fee_percent=serializer.validated_data['service_fee_percent'],
            tables_payload=serializer.validated_data['tables'],
            deleted_table_ids=serializer.validated_data.get('deleted_table_ids', []),
        )
        hall = self.get_queryset().get(pk=hall.pk)
        return response.Response(HallConstructorSerializer(hall).data)
