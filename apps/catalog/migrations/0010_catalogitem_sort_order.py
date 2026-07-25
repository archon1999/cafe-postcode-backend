from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0009_modifiergroup_modifieroption_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogitem',
            name='sort_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='catalogitem',
            options={'ordering': ('sort_order', 'name')},
        ),
    ]
