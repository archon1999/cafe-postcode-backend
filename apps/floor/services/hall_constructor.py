from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.floor.models import DiningTable, Hall, TableSession


@dataclass(frozen=True)
class _Placement:
    table_id: str
    position_x: int
    position_y: int
    width: int
    height: int

    @property
    def max_x(self):
        return self.position_x + self.width

    @property
    def max_y(self):
        return self.position_y + self.height


class HallConstructorService:
    def validate_layout(
        self,
        *,
        hall: Hall,
        grid_columns: int,
        tables_payload: list[dict],
        deleted_table_ids: Iterable[str],
    ):
        existing_tables = {str(table.id): table for table in hall.tables.all()}
        deleted_table_ids = {str(table_id) for table_id in deleted_table_ids}
        payload_ids = {str(item['id']) for item in tables_payload if item.get('id')}

        submitted_payload_ids = [
            str(item['id']) for item in tables_payload if item.get('id')
        ]
        if len(submitted_payload_ids) != len(payload_ids):
            raise ValidationError({'tables': _('A table may be submitted only once.')})

        unknown_deleted_ids = deleted_table_ids - set(existing_tables.keys())
        if unknown_deleted_ids:
            raise ValidationError({'deleted_table_ids': _('One or more tables do not belong to this hall.')})

        unknown_payload_ids = payload_ids - set(existing_tables.keys())
        if unknown_payload_ids:
            raise ValidationError({'tables': _('One or more tables do not belong to this hall.')})

        if payload_ids & deleted_table_ids:
            raise ValidationError(
                {'deleted_table_ids': _('The same table cannot be updated and deleted at the same time.')}
            )

        missing_existing_ids = set(existing_tables.keys()) - deleted_table_ids - payload_ids
        if missing_existing_ids:
            raise ValidationError({'tables': _('Full hall snapshot is required when saving constructor data.')})

        if deleted_table_ids and DiningTable.objects.filter(
            id__in=deleted_table_ids,
            hall=hall,
            table_sessions__status__in=(
                TableSession.Status.OPEN,
                TableSession.Status.PENDING_PAYMENT,
            ),
        ).exists():
            raise ValidationError(
                {
                    'deleted_table_ids': _(
                        'Close or move active table sessions before deleting a table.'
                    )
                }
            )

        placements: list[_Placement] = []
        table_numbers: set[int] = set()

        for item in tables_payload:
            table_id = str(item.get('id') or item['table_number'])
            seat_count = item['seat_count']
            shape_variant = item['shape_variant']

            if shape_variant not in DiningTable.get_supported_variants_for_seat_count(seat_count):
                raise ValidationError({'tables': _('Shape variant does not match the selected seat count.')})

            table_number = item['table_number']
            if table_number in table_numbers:
                raise ValidationError({'tables': _('Table numbers must be unique inside a hall.')})
            table_numbers.add(table_number)

            placement = _Placement(
                table_id=table_id,
                position_x=item['position_x'],
                position_y=item['position_y'],
                width=item['width'],
                height=item['height'],
            )

            if placement.max_x > grid_columns:
                raise ValidationError({'tables': _('One or more tables exceed the configured grid width.')})

            for existing_placement in placements:
                if self._placements_overlap(existing_placement, placement):
                    raise ValidationError({'tables': _('Tables cannot overlap inside the hall constructor grid.')})

            placements.append(placement)

    @transaction.atomic
    def save_layout(
        self,
        *,
        hall: Hall,
        grid_columns: int,
        service_fee_enabled: bool,
        service_fee_mode: str,
        service_fee_percent,
        service_fee_hourly_rate: int,
        tables_payload: list[dict],
        deleted_table_ids: Iterable[str],
    ):
        hall = Hall.objects.select_for_update(of=('self',)).get(pk=hall.pk)
        deleted_table_ids = {str(table_id) for table_id in deleted_table_ids}
        self.validate_layout(
            hall=hall,
            grid_columns=grid_columns,
            tables_payload=tables_payload,
            deleted_table_ids=deleted_table_ids,
        )

        existing_tables = {str(table.id): table for table in hall.tables.all()}

        if deleted_table_ids:
            DiningTable.objects.filter(id__in=deleted_table_ids, hall=hall).delete()

        for item in tables_payload:
            table = existing_tables.get(str(item.get('id')))
            defaults = {
                'name': item['name'].strip(),
                'table_number': item['table_number'],
                'seat_count': item['seat_count'],
                'shape_variant': item['shape_variant'],
                'shape': DiningTable.infer_shape_from_variant(item['shape_variant']),
                'position_x': item['position_x'],
                'position_y': item['position_y'],
                'width': item['width'],
                'height': item['height'],
                'rotation': 0,
                'service_fee_enabled': item.get('service_fee_enabled', False),
                'service_fee_mode': item.get('service_fee_mode', 'percentage'),
                'service_fee_percent': item.get('service_fee_percent', 0),
                'service_fee_hourly_rate': item.get('service_fee_hourly_rate', 0),
                'is_active': item.get('is_active', True),
            }

            if table is None:
                DiningTable.objects.create(
                    hall=hall,
                    zone=None,
                    status=DiningTable.Status.AVAILABLE,
                    **defaults,
                )
                continue

            for field_name, value in defaults.items():
                setattr(table, field_name, value)
            table.save()

        hall.grid_columns = grid_columns
        hall.service_fee_enabled = service_fee_enabled
        hall.service_fee_mode = service_fee_mode
        hall.service_fee_percent = service_fee_percent
        hall.service_fee_hourly_rate = service_fee_hourly_rate
        hall.save(
            update_fields=[
                'grid_columns',
                'service_fee_enabled',
                'service_fee_mode',
                'service_fee_percent',
                'service_fee_hourly_rate',
                'updated_at',
            ]
        )
        hall.refresh_from_db()
        return hall

    def _placements_overlap(self, left: _Placement, right: _Placement):
        return not (
            left.max_x <= right.position_x
            or right.max_x <= left.position_x
            or left.max_y <= right.position_y
            or right.max_y <= left.position_y
        )
