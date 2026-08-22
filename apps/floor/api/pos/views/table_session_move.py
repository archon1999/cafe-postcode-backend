from uuid import UUID

from django.utils.translation import gettext as _
from rest_framework import permissions
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.services import TableOperationService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class TableSessionMoveView(APIView):
    """Backward-compatible endpoint that only moves to an empty table."""

    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = TableOperationService

    def post(self, request, pk):
        try:
            target_table_id = UUID(str(request.data.get('target_table_id')))
        except (TypeError, ValueError, AttributeError):
            raise NotFound(_('Table was not found.')) from None
        result = self.service_class().transfer(
            source_session_id=pk,
            target_table_id=target_table_id,
            expected_target_session_ids=[],
            restaurant=get_request_restaurant(request),
            actor=request.user,
        )
        return Response(TableSessionSerializer(result['session'], context={'request': request}).data)
