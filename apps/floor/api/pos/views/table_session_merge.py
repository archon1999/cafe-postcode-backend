from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.models import DiningTable, TableSession
from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.services import sync_table_status
from apps.sales.helpers import get_order_model
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

Order = get_order_model()


class TableSessionMergeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        target_session = generics.get_object_or_404(
            TableSession,
            pk=pk,
            restaurant=restaurant,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        source_session = generics.get_object_or_404(
            TableSession,
            pk=request.data.get('source_session_id'),
            restaurant=restaurant,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        if source_session.pk == target_session.pk:
            return Response({'detail': _('Cannot merge a session into itself.')}, status=status.HTTP_400_BAD_REQUEST)

        Order.objects.filter(table_session=source_session).update(table_session=target_session)
        source_session.status = TableSession.Status.MERGED
        source_session.merged_into = target_session
        source_session.closed_at = timezone.now()
        source_session.save(update_fields=['status', 'merged_into', 'closed_at', 'updated_at'])

        sync_table_status(source_session.table)
        sync_table_status(target_session.table)
        return Response(TableSessionSerializer(target_session).data)
