from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0019_alter_cashshift_expected_closing_cash_amount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fiscalshiftsession',
            name='edge_session_id',
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddConstraint(
            model_name='fiscalshiftsession',
            constraint=models.UniqueConstraint(
                fields=('restaurant', 'edge_session_id'),
                name='fiscalshift_rest_edge_session_uniq',
            ),
        ),
    ]
