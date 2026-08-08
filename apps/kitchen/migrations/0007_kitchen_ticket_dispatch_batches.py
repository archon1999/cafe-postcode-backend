import uuid

import django.db.models.deletion
from django.db import migrations, models


def backfill_ticket_lines(apps, schema_editor):
    KitchenTicket = apps.get_model('kitchen', 'KitchenTicket')
    KitchenTicketLine = apps.get_model('kitchen', 'KitchenTicketLine')
    OrderItem = apps.get_model('sales', 'OrderItem')

    lines = []
    for ticket in KitchenTicket.objects.all().iterator():
        item_ids = OrderItem.objects.filter(
            order_id=ticket.order_id,
            prep_station_id=ticket.prep_station_id,
        ).exclude(status='cancelled').values_list('id', flat=True)
        lines.extend(
            KitchenTicketLine(ticket_id=ticket.id, order_item_id=item_id)
            for item_id in item_ids
        )
    KitchenTicketLine.objects.bulk_create(lines, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('kitchen', '0006_kitchenannouncement'),
        ('sales', '0009_orderitem_base_unit_price_orderitemmodifier'),
    ]

    operations = [
        migrations.AddField(
            model_name='kitchenticket',
            name='dispatch_number',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='kitchenticket',
            name='handed_off_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterUniqueTogether(
            name='kitchenticket',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='kitchenticket',
            constraint=models.UniqueConstraint(
                fields=('order', 'prep_station', 'dispatch_number'),
                name='kitchen_ticket_order_station_dispatch_uniq',
            ),
        ),
        migrations.CreateModel(
            name='KitchenTicketLine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order_item', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='kitchen_ticket_line', to='sales.orderitem')),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='kitchen.kitchenticket')),
            ],
            options={
                'ordering': ('created_at',),
                'indexes': [models.Index(fields=['ticket', 'created_at'], name='kt_line_ticket_created_idx')],
            },
        ),
        migrations.RunPython(backfill_ticket_lines, migrations.RunPython.noop),
    ]
