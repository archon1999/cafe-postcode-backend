from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.api.pos.serializers.table_operations import (
    TableGroupSerializer,
    TableTransferSerializer,
    TableUngroupSerializer,
)
from apps.floor.services import TableOperationService, session_physical_tables
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


def _session_payload(request, session):
    return TableSessionSerializer(session, context={'request': request}).data


class TableSessionTransferView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = TableOperationService

    def post(self, request, pk):
        serializer = TableTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = self.service_class().transfer(
            source_session_id=pk,
            restaurant=get_request_restaurant(request),
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            {
                'mode': result['mode'],
                'session': _session_payload(request, result['session']),
                'released_table_ids': [str(table.pk) for table in result['released_tables']],
            },
            status=status.HTTP_200_OK,
        )


class TableSessionGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = TableOperationService

    def post(self, request, pk):
        serializer = TableGroupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = self.service_class().group(
            session_id=pk,
            restaurant=get_request_restaurant(request),
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            {
                'mode': 'grouped',
                'session': _session_payload(request, session),
                'table_ids': [str(table.pk) for table in session_physical_tables(session)],
            },
            status=status.HTTP_200_OK,
        )


class TableSessionUngroupView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = TableOperationService

    def post(self, request, pk):
        serializer = TableUngroupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = self.service_class().ungroup(
            session_id=pk,
            restaurant=get_request_restaurant(request),
            **serializer.validated_data,
        )
        return Response(
            {
                'mode': 'ungrouped',
                'session': _session_payload(request, session),
                'table_ids': [str(table.pk) for table in session_physical_tables(session)],
            },
            status=status.HTTP_200_OK,
        )
