from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0013_receipt_plain_print_document'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='edge_operation_id',
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
    ]
