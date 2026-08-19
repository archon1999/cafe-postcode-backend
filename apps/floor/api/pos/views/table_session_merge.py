from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
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
        try:
            target_session_id = UUID(str(pk))
            source_session_id = UUID(str(request.data.get('source_session_id')))
        except (TypeError, ValueError, AttributeError):
            raise NotFound(_('Table session was not found.')) from None

        if source_session_id == target_session_id:
            return Response({'detail': _('Cannot merge a session into itself.')}, status=status.HTTP_400_BAD_REQUEST)

        locked_sessions = {
            session.pk: session
            for session in TableSession.objects.select_for_update(of=('self',))
            .select_related('table')
            .filter(
                pk__in=(target_session_id, source_session_id),
                restaurant=restaurant,
                status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
            )
            .order_by('pk')
        }
        target_session = locked_sessions.get(target_session_id)
        source_session = locked_sessions.get(source_session_id)
        if target_session is None or source_session is None:
            raise NotFound(_('Table session was not found.'))

        list(
            DiningTable.objects.select_for_update(of=('self',))
            .filter(pk__in=(target_session.table_id, source_session.table_id))
            .order_by('pk')
        )

        Order.objects.filter(table_session=source_session).update(table_session=target_session)
        source_session.status = TableSession.Status.MERGED
        source_session.merged_into = target_session
        source_session.closed_at = timezone.now()
        source_session.save(update_fields=['status', 'merged_into', 'closed_at', 'updated_at'])

        sync_table_status(source_session.table)
        sync_table_status(target_session.table)
        return Response(TableSessionSerializer(target_session).data)
