from decimal import Decimal

from django.db import migrations, models


def migrate_kpi_salary_type(apps, schema_editor):
    EmployeeCompensationProfile = apps.get_model('accounts', 'EmployeeCompensationProfile')

    EmployeeCompensationProfile.objects.filter(salary_type='kpi').update(
        salary_type='monthly',
        base_amount=Decimal('0.00'),
    )


def reverse_kpi_salary_type(apps, schema_editor):
    EmployeeCompensationProfile = apps.get_model('accounts', 'EmployeeCompensationProfile')

    EmployeeCompensationProfile.objects.filter(
        salary_type='monthly',
        base_amount=Decimal('0.00'),
    ).update(salary_type='kpi')


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_alter_permissionendpoint_unique_constraint'),
    ]

    operations = [
        migrations.RunPython(migrate_kpi_salary_type, reverse_kpi_salary_type),
        migrations.AlterField(
            model_name='employeecompensationprofile',
            name='salary_type',
            field=models.CharField(
                blank=True,
                choices=[('hourly', 'Hourly'), ('daily', 'Daily'), ('monthly', 'Monthly')],
                default='',
                max_length=16,
            ),
        ),
    ]
