from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0006_catalogitem_marking'),
        ('sales', '0005_order_open_check_indexes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderItemMarking',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('raw_code', models.CharField(max_length=512)),
                ('gtin', models.CharField(blank=True, db_index=True, max_length=32)),
                ('serial', models.CharField(blank=True, max_length=256)),
                ('scanned_at', models.DateTimeField(default=django.utils.timezone.now)),
                (
                    'catalog_item',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='order_item_markings',
                        to='catalog.catalogitem',
                    ),
                ),
                (
                    'order_item',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='markings',
                        to='sales.orderitem',
                    ),
                ),
                (
                    'scanned_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='scanned_order_item_markings',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ('scanned_at', 'created_at'),
            },
        ),
        migrations.AddConstraint(
            model_name='orderitemmarking',
            constraint=models.UniqueConstraint(fields=('catalog_item', 'raw_code'), name='uniq_order_item_marking_catalog_raw'),
        ),
        migrations.AddIndex(
            model_name='orderitemmarking',
            index=models.Index(fields=['order_item', 'gtin'], name='order_mark_item_gtin_idx'),
        ),
    ]
