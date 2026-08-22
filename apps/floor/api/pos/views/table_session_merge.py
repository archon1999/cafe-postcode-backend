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


class TableSessionMergeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = TableOperationService

    def post(self, request, pk):
        try:
            source_session_id = UUID(str(request.data.get('source_session_id')))
        except (TypeError, ValueError, AttributeError):
            raise NotFound(_('Table session was not found.')) from None
        session = self.service_class().merge(
            source_session_id=source_session_id,
            target_session_id=pk,
            restaurant=get_request_restaurant(request),
            actor=request.user,
        )
        return Response(TableSessionSerializer(session, context={'request': request}).data)
