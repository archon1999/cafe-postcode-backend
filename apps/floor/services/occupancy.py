from django.db.models import Sum

from apps.floor.models import DiningTable, TableSession


ACTIVE_SESSION_STATUSES = (TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT)


def active_table_sessions(table):
    return TableSession.objects.filter(table_id=table.pk, status__in=ACTIVE_SESSION_STATUSES)


def occupied_guest_count(table, *, exclude_session=None) -> int:
    queryset = active_table_sessions(table)
    if exclude_session is not None:
        queryset = queryset.exclude(pk=getattr(exclude_session, 'pk', exclude_session))
    return int(queryset.aggregate(total=Sum('guest_count')).get('total') or 0)


def available_seat_count(table, *, exclude_session=None) -> int:
    return max(int(table.seat_count or 0) - occupied_guest_count(table, exclude_session=exclude_session), 0)


def sync_table_status(table):
    table = DiningTable.objects.get(pk=table.pk)
    if table.status == DiningTable.Status.BLOCKED:
        return table
    has_active_sessions = active_table_sessions(table).exists()
    next_status = DiningTable.Status.OCCUPIED if has_active_sessions else DiningTable.Status.AVAILABLE
    if table.status != next_status:
        table.status = next_status
        table.save(update_fields=['status', 'updated_at'])
    return table
