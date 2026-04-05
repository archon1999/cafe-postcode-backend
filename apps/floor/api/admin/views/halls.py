from django.shortcuts import get_object_or_404
from rest_framework import generics, response, views

from apps.floor.api.admin.serializers import (
    HallConstructorSerializer,
    HallConstructorUpdateSerializer,
    HallSerializer,
)
from apps.floor.models import Hall
from apps.floor.selectors.floor import HallListFilters, hall_constructor_queryset
from apps.floor.services import HallConstructorService
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class HallListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = HallSerializer

    def get_queryset(self):
        queryset = (
            Hall.objects.all()
            .select_related('zone_or_cabin')
            .prefetch_related('tables__table_sessions')
        )
        queryset = filter_queryset_by_optional_restaurant(queryset, self.request, lookup='zone_or_cabin__restaurant')
        return HallListFilters.from_request(self.request).apply(queryset)


class HallDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = HallSerializer

    def get_queryset(self):
        return (
            filter_queryset_by_optional_restaurant(Hall.objects.all(), self.request, lookup='zone_or_cabin__restaurant')
            .select_related('zone_or_cabin')
            .prefetch_related('tables__table_sessions')
        )


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
            tables_payload=serializer.validated_data['tables'],
            deleted_table_ids=serializer.validated_data.get('deleted_table_ids', []),
        )
        hall = self.get_queryset().get(pk=hall.pk)
        return response.Response(HallConstructorSerializer(hall).data)

__all__ = ['HallConstructorView', 'HallDetailView', 'HallListCreateView']
