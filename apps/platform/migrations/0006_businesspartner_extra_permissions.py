from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('platform', '0005_restaurantbalancetransaction'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='businesspartner',
            name='extra_permissions',
            field=models.ManyToManyField(blank=True, related_name='business_partners', to='users.permission'),
        ),
    ]
