from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.models import DiningTable, TableSession
from apps.floor.serializers import TableSessionSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class TableSessionMergeView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'table.manage'

    @transaction.atomic
    def post(self, request, pk):
        from apps.orders.models import Order

        branch = get_request_branch(request)
        target_session = generics.get_object_or_404(
            TableSession,
            pk=pk,
            branch=branch,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        source_session = generics.get_object_or_404(
            TableSession,
            pk=request.data.get('source_session_id'),
            branch=branch,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        if source_session.pk == target_session.pk:
            return Response({'detail': _('Cannot merge a session into itself.')}, status=status.HTTP_400_BAD_REQUEST)

        Order.objects.filter(table_session=source_session).update(table_session=target_session)
        source_session.status = TableSession.Status.MERGED
        source_session.merged_into = target_session
        source_session.closed_at = timezone.now()
        source_session.save(update_fields=['status', 'merged_into', 'closed_at', 'updated_at'])

        source_session.table.status = DiningTable.Status.AVAILABLE
        source_session.table.save(update_fields=['status', 'updated_at'])
        return Response(TableSessionSerializer(target_session).data)
