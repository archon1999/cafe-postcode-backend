from django.db import migrations, models


def backfill_order_item_created_by(apps, schema_editor):
    Order = apps.get_model('sales', 'Order')
    OrderItem = apps.get_model('sales', 'OrderItem')
    OrderItem.objects.filter(created_by__isnull=True, order__opened_by__isnull=False).update(
        created_by_id=models.Subquery(
            Order.objects.filter(pk=models.OuterRef('order_id')).values('opened_by_id')[:1]
        )
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('sales', '0006_orderitemmarking'),
    ]

    operations = [
        migrations.RunPython(backfill_order_item_created_by, noop_reverse),
    ]
