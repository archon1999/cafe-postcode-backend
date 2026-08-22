from django.db.models import Q, Sum

from apps.floor.models import DiningTable, TableSession


ACTIVE_SESSION_STATUSES = (TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT)
PREFETCHED_ACTIVE_TABLE_LINKS_ATTR = 'serialized_active_table_links'


def active_table_sessions(table):
    return TableSession.objects.filter(
        Q(table_id=table.pk)
        | Q(
            attached_table_links__table_id=table.pk,
            attached_table_links__released_at__isnull=True,
        ),
        status__in=ACTIVE_SESSION_STATUSES,
    ).distinct()


def session_physical_tables(session):
    prefetched_links = getattr(session, PREFETCHED_ACTIVE_TABLE_LINKS_ATTR, None)
    if prefetched_links is not None:
        links = prefetched_links
    else:
        links = session.attached_table_links.filter(released_at__isnull=True).select_related('table')
    attached_tables = [
        link.table
        for link in links
    ]
    return [session.table, *[table for table in attached_tables if table.pk != session.table_id]]


def session_seat_count(session) -> int:
    return sum(int(table.seat_count or 0) for table in session_physical_tables(session))


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


def sync_session_table_statuses(session):
    return [sync_table_status(table) for table in session_physical_tables(session)]
