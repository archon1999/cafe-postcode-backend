import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0007_user_business_partner'),
        ('floor', '0007_alter_hall_unique_together_and_more'),
        ('organizations', '0012_alter_cashdesk_branch_alter_device_branch_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='BusinessPartnerUserProfile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'business_partner',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='user_profiles',
                        to='organizations.businesspartner',
                    ),
                ),
                (
                    'user',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='business_partner_user_profile',
                        to='accounts.user',
                    ),
                ),
            ],
            options={
                'ordering': ('user__username',),
            },
        ),
        migrations.CreateModel(
            name='RestaurantUserProfile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('pin_code', models.CharField(blank=True, default='', max_length=128)),
                ('hall_switch_permission', models.BooleanField(default=False)),
                (
                    'primary_hall',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='primary_restaurant_users',
                        to='floor.hall',
                    ),
                ),
                (
                    'restaurant',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='user_profiles',
                        to='organizations.restaurant',
                    ),
                ),
                (
                    'user',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='restaurant_profile',
                        to='accounts.user',
                    ),
                ),
                (
                    'allowed_halls',
                    models.ManyToManyField(blank=True, related_name='restaurant_allowed_users', to='floor.hall'),
                ),
            ],
            options={
                'ordering': ('user__username',),
            },
        ),
    ]
