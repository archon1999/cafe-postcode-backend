from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0021_restaurant_pos_monitor_variant'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='parent_restaurant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='branches',
                to='restaurants.restaurant',
            ),
        ),
        migrations.AddConstraint(
            model_name='restaurant',
            constraint=models.CheckConstraint(
                check=~models.Q(id=models.F('parent_restaurant_id')),
                name='restaurant_parent_not_self',
            ),
        ),
    ]
