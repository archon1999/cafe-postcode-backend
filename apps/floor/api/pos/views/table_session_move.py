from uuid import UUID

from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.floor.models import DiningTable, TableSession
from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.services import available_seat_count, sync_table_status
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class TableSessionMoveView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        session = generics.get_object_or_404(
            TableSession.objects.select_for_update(of=('self',)).select_related('table', 'hall'),
            pk=pk,
            restaurant=restaurant,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        try:
            target_table_id = UUID(str(request.data.get('target_table_id')))
        except (TypeError, ValueError, AttributeError):
            raise NotFound(_('Table was not found.')) from None

        locked_tables = {
            table.pk: table
            for table in DiningTable.objects.select_for_update(of=('self',))
            .select_related('hall')
            .filter(
                pk__in=(session.table_id, target_table_id),
                hall__zone_or_cabin__restaurant=restaurant,
            )
            .order_by('pk')
        }
        previous_table = locked_tables.get(session.table_id)
        target_table = locked_tables.get(target_table_id)
        if previous_table is None or target_table is None:
            raise NotFound(_('Table was not found.'))

        if session.guest_count > available_seat_count(target_table):
            return Response({'detail': _('Target table does not have enough available seats.')}, status=status.HTTP_400_BAD_REQUEST)

        session.table = target_table
        session.hall = target_table.hall
        session.save(update_fields=['table', 'hall', 'updated_at'])

        target_table.status = DiningTable.Status.OCCUPIED
        target_table.save(update_fields=['status', 'updated_at'])
        sync_table_status(previous_table)
        sync_table_status(target_table)
        return Response(TableSessionSerializer(session).data)
