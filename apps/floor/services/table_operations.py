from collections import defaultdict

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound

from apps.floor.models import DiningTable, TableSession, TableSessionTable
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order

from .occupancy import (
    ACTIVE_SESSION_STATUSES,
    active_table_sessions,
    session_physical_tables,
    sync_table_status,
)


ACTIVE_ORDER_STATUSES = (Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY)


class TableOperationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'table_operation_conflict'


class TableOperationService:
    def _error(self, code, detail, *, field='detail'):
        raise serializers.ValidationError({'code': code, field: detail})

    def _lock_session(self, *, session_id, restaurant):
        try:
            return (
                TableSession.objects.select_for_update(of=('self',))
                .select_related('table', 'hall')
                .get(
                    pk=session_id,
                    restaurant=restaurant,
                    status__in=ACTIVE_SESSION_STATUSES,
                )
            )
        except TableSession.DoesNotExist:
            raise NotFound(_('Table session was not found.')) from None

    def _lock_tables(self, *, table_ids, restaurant):
        unique_ids = {str(table_id) for table_id in table_ids}
        tables = {
            str(table.pk): table
            for table in DiningTable.objects.select_for_update(of=('self',))
            .select_related('hall')
            .filter(
                pk__in=list(unique_ids),
                hall__zone_or_cabin__restaurant=restaurant,
                is_active=True,
            )
            .order_by('pk')
        }
        if len(tables) != len(unique_ids):
            raise NotFound(_('One or more tables were not found.'))
        return tables

    def _active_sessions_for_table(self, table):
        session_ids = list(active_table_sessions(table).values_list('pk', flat=True))
        return list(
            TableSession.objects.select_for_update(of=('self',))
            .filter(pk__in=session_ids, status__in=ACTIVE_SESSION_STATUSES)
            .select_related('table', 'hall')
            .order_by('created_at', 'pk')
        )

    def _validate_mergeable_sessions(self, sessions):
        if any(session.status == TableSession.Status.PENDING_PAYMENT for session in sessions):
            self._error(
                'TABLE_PAYMENT_IN_PROGRESS',
                _('A table with a payment in progress cannot be merged.'),
            )

        active_orders = list(
            Order.objects.select_for_update(of=('self',))
            .filter(table_session__in=sessions, status__in=ACTIVE_ORDER_STATUSES)
            .select_related('table_session')
            .order_by('-created_at', 'pk')
        )
        blocked_order = next(
            (
                order
                for order in active_orders
                if order.total_override is not None or order.payments.exists() or order.receipts.exists()
            ),
            None,
        )
        if blocked_order is not None:
            self._error(
                'TABLE_ORDER_PAYMENT_STARTED',
                _('A check with a payment or manual total cannot be merged.'),
            )
        return active_orders

    @staticmethod
    def _combine_notes(*values):
        notes = []
        for value in values:
            note = str(value or '').strip()
            if note and note not in notes:
                notes.append(note)
        return '\n'.join(notes)

    def _move_kitchen_tickets(self, *, source_order, target_order):
        next_dispatch = defaultdict(int)
        for row in (
            KitchenTicket.objects.filter(order=target_order)
            .values('prep_station_id')
            .annotate(value=Max('dispatch_number'))
        ):
            next_dispatch[row['prep_station_id']] = int(row['value'] or 0)

        for ticket in (
            KitchenTicket.objects.select_for_update(of=('self',))
            .filter(order=source_order)
            .order_by('created_at', 'pk')
        ):
            next_dispatch[ticket.prep_station_id] += 1
            ticket.order = target_order
            ticket.dispatch_number = next_dispatch[ticket.prep_station_id]
            ticket.save(update_fields=['order', 'dispatch_number', 'updated_at'])

    def _consolidate_orders(self, *, sessions, canonical_session):
        active_orders = self._validate_mergeable_sessions(sessions)
        target_orders = [order for order in active_orders if order.table_session_id == canonical_session.pk]
        canonical_order = target_orders[0] if target_orders else (active_orders[0] if active_orders else None)
        if canonical_order is None:
            return None

        if canonical_order.table_session_id != canonical_session.pk:
            canonical_order.table_session = canonical_session
            canonical_order.save(update_fields=['table_session', 'updated_at'])

        now = timezone.now()
        for source_order in active_orders:
            if source_order.pk == canonical_order.pk:
                continue
            self._move_kitchen_tickets(source_order=source_order, target_order=canonical_order)
            source_order.items.update(order=canonical_order, updated_at=now)
            canonical_order.note = self._combine_notes(canonical_order.note, source_order.note)
            source_order.status = Order.Status.CANCELLED
            source_order.closed_at = now
            source_order.subtotal = 0
            source_order.calculated_total = 0
            source_order.total = 0
            source_order.save(
                update_fields=[
                    'status',
                    'closed_at',
                    'subtotal',
                    'calculated_total',
                    'total',
                    'updated_at',
                ]
            )

        canonical_order.guest_count = canonical_session.guest_count
        canonical_order.save(update_fields=['guest_count', 'note', 'updated_at'])
        canonical_order.recalculate_totals()
        return canonical_order

    def _release_secondary_tables(self, session, *, now=None):
        now = now or timezone.now()
        links = list(
            TableSessionTable.objects.select_for_update(of=('self',))
            .select_related('table')
            .filter(session=session, released_at__isnull=True)
        )
        if links:
            TableSessionTable.objects.filter(pk__in=[link.pk for link in links]).update(
                released_at=now,
                updated_at=now,
            )
        return [link.table for link in links]

    def _attach_table(self, *, session, table, actor):
        if table.pk == session.table_id:
            return
        link, _ = TableSessionTable.objects.select_for_update(of=('self',)).get_or_create(
            session=session,
            table=table,
            defaults={'joined_by': actor},
        )
        if link.released_at is not None or link.joined_by_id != getattr(actor, 'pk', None):
            link.released_at = None
            link.joined_by = actor
            link.save(update_fields=['released_at', 'joined_by', 'updated_at'])

    def _merge_session(self, *, source, target, actor, retain_source_tables):
        if source.pk == target.pk:
            return target

        source_tables = session_physical_tables(source)
        target_tables = session_physical_tables(target)
        self._validate_mergeable_sessions([source, target])

        target.guest_count = int(target.guest_count or 0) + int(source.guest_count or 0)
        target.note = self._combine_notes(target.note, source.note)
        target.save(update_fields=['guest_count', 'note', 'updated_at'])
        self._consolidate_orders(sessions=[target, source], canonical_session=target)

        now = timezone.now()
        self._release_secondary_tables(source, now=now)
        source.status = TableSession.Status.MERGED
        source.merged_into = target
        source.closed_at = now
        source.save(update_fields=['status', 'merged_into', 'closed_at', 'updated_at'])

        if retain_source_tables:
            for table in source_tables:
                self._attach_table(session=target, table=table, actor=actor)

        for table in {table.pk: table for table in [*source_tables, *target_tables]}.values():
            sync_table_status(table)
        return target

    @transaction.atomic
    def transfer(
        self,
        *,
        source_session_id,
        target_table_id,
        restaurant,
        actor,
        target_session_id=None,
        expected_target_session_ids=None,
    ):
        source = self._lock_session(session_id=source_session_id, restaurant=restaurant)
        source_tables = session_physical_tables(source)
        tables = self._lock_tables(
            table_ids=[*[table.pk for table in source_tables], target_table_id],
            restaurant=restaurant,
        )
        target_table = tables[str(target_table_id)]
        if target_table.status == DiningTable.Status.BLOCKED:
            self._error('TARGET_TABLE_BLOCKED', _('The target table is blocked.'))
        if target_table.status == DiningTable.Status.RESERVED:
            self._error('TARGET_TABLE_RESERVED', _('A reserved table cannot receive a transfer.'))
        if any(table.pk == target_table.pk for table in source_tables):
            self._error('SOURCE_AND_TARGET_MATCH', _('The source and target tables must be different.'))

        target_sessions = [
            session for session in self._active_sessions_for_table(target_table) if session.pk != source.pk
        ]
        actual_target_ids = {str(session.pk) for session in target_sessions}
        if expected_target_session_ids is not None and actual_target_ids != {
            str(value) for value in expected_target_session_ids
        }:
            raise TableOperationConflict(
                {
                    'code': 'TARGET_TABLE_CHANGED',
                    'detail': _('The target table changed. Refresh the hall and confirm again.'),
                }
            )

        if not target_sessions:
            released_tables = self._release_secondary_tables(source)
            previous_table = source.table
            source.table = target_table
            source.hall = target_table.hall
            source.save(update_fields=['table', 'hall', 'updated_at'])
            for table in {table.pk: table for table in [previous_table, *released_tables, target_table]}.values():
                sync_table_status(table)
            return {'mode': 'moved', 'session': source, 'released_tables': [previous_table, *released_tables]}

        if target_session_id is None:
            if len(target_sessions) != 1:
                self._error(
                    'TARGET_SESSION_REQUIRED',
                    _('Select which active check on the target table should receive this table.'),
                    field='target_session_id',
                )
            target = target_sessions[0]
        else:
            target = next((session for session in target_sessions if str(session.pk) == str(target_session_id)), None)
            if target is None:
                self._error('TARGET_SESSION_NOT_FOUND', _('The selected target check is no longer active.'))

        target_capacity = sum(int(table.seat_count or 0) for table in session_physical_tables(target))
        combined_guests = int(target.guest_count or 0) + int(source.guest_count or 0)
        if combined_guests > target_capacity:
            self._error(
                'TARGET_TABLE_CAPACITY_EXCEEDED',
                _('The target table group does not have enough seats.'),
            )

        target = self._merge_session(source=source, target=target, actor=actor, retain_source_tables=False)
        return {'mode': 'merged', 'session': target, 'released_tables': source_tables}

    @transaction.atomic
    def group(self, *, session_id, table_ids, restaurant, actor):
        canonical = self._lock_session(session_id=session_id, restaurant=restaurant)
        if canonical.status == TableSession.Status.PENDING_PAYMENT:
            self._error('TABLE_PAYMENT_IN_PROGRESS', _('Tables cannot be grouped while payment is in progress.'))

        requested_ids = {str(table_id) for table_id in table_ids if str(table_id) != str(canonical.table_id)}
        current_tables = session_physical_tables(canonical)
        tables = self._lock_tables(
            table_ids=[*[table.pk for table in current_tables], *requested_ids],
            restaurant=restaurant,
        )
        requested_tables = [tables[table_id] for table_id in requested_ids]
        if any(table.hall_id != canonical.hall_id for table in requested_tables):
            self._error('TABLE_GROUP_HALL_MISMATCH', _('Only tables from the same hall can be grouped.'))
        if any(table.status == DiningTable.Status.BLOCKED for table in requested_tables):
            self._error('TABLE_GROUP_BLOCKED', _('Blocked tables cannot be grouped.'))
        if any(table.status == DiningTable.Status.RESERVED for table in requested_tables):
            self._error('TABLE_GROUP_RESERVED', _('Reserved tables cannot be grouped.'))

        involved_sessions = {canonical.pk: canonical}
        for table in requested_tables:
            for active_session in self._active_sessions_for_table(table):
                involved_sessions[active_session.pk] = active_session
        self._validate_mergeable_sessions(list(involved_sessions.values()))

        all_physical_tables = {table.pk: table for table in current_tables}
        for active_session in involved_sessions.values():
            for table in session_physical_tables(active_session):
                all_physical_tables[table.pk] = table
        for table in requested_tables:
            all_physical_tables[table.pk] = table
        combined_capacity = sum(int(table.seat_count or 0) for table in all_physical_tables.values())
        combined_guests = sum(int(session.guest_count or 0) for session in involved_sessions.values())
        if combined_guests > combined_capacity:
            self._error('TABLE_GROUP_CAPACITY_EXCEEDED', _('The selected tables do not have enough total seats.'))

        for source in list(involved_sessions.values()):
            if source.pk != canonical.pk:
                canonical = self._merge_session(
                    source=source,
                    target=canonical,
                    actor=actor,
                    retain_source_tables=True,
                )
        for table in requested_tables:
            self._attach_table(session=canonical, table=table, actor=actor)
            sync_table_status(table)
        sync_table_status(canonical.table)
        return canonical

    @transaction.atomic
    def merge(self, *, source_session_id, target_session_id, restaurant, actor):
        sessions = {
            str(session.pk): session
            for session in TableSession.objects.select_for_update(of=('self',))
            .select_related('table', 'hall')
            .filter(
                pk__in=(source_session_id, target_session_id),
                restaurant=restaurant,
                status__in=ACTIVE_SESSION_STATUSES,
            )
            .order_by('pk')
        }
        source = sessions.get(str(source_session_id))
        target = sessions.get(str(target_session_id))
        if source is None or target is None:
            raise NotFound(_('Table session was not found.'))
        if source.pk == target.pk:
            self._error('SOURCE_AND_TARGET_MATCH', _('Cannot merge a session into itself.'))
        self._lock_tables(
            table_ids=[
                *[table.pk for table in session_physical_tables(source)],
                *[table.pk for table in session_physical_tables(target)],
            ],
            restaurant=restaurant,
        )
        return self._merge_session(
            source=source,
            target=target,
            actor=actor,
            retain_source_tables=False,
        )

    @transaction.atomic
    def ungroup(self, *, session_id, table_ids, restaurant):
        canonical = self._lock_session(session_id=session_id, restaurant=restaurant)
        queryset = TableSessionTable.objects.select_for_update(of=('self',)).select_related('table').filter(
            session=canonical,
            released_at__isnull=True,
        )
        if table_ids:
            queryset = queryset.filter(table_id__in=table_ids)
        links = list(queryset)
        now = timezone.now()
        if links:
            TableSessionTable.objects.filter(pk__in=[link.pk for link in links]).update(
                released_at=now,
                updated_at=now,
            )
        for link in links:
            sync_table_status(link.table)
        sync_table_status(canonical.table)
        return canonical
