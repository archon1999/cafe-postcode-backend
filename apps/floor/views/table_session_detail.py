from rest_framework import generics, permissions

from apps.floor.models import TableSession
from apps.floor.serializers import TableSessionSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class TableSessionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'table.manage'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return TableSession.objects.filter(branch=branch).select_related('table', 'hall', 'opened_by', 'assigned_waiter')
