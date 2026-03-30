from django.db import migrations


def backfill_branch_fiscal_profile(apps, schema_editor):
    Branch = apps.get_model('organizations', 'Branch')

    for branch in Branch.objects.select_related('restaurant').all():
        updates = []
        if not branch.legal_name and branch.restaurant and branch.restaurant.legal_name:
            branch.legal_name = branch.restaurant.legal_name
            updates.append('legal_name')
        if not branch.tax_number and branch.restaurant and branch.restaurant.tax_number:
            branch.tax_number = branch.restaurant.tax_number
            updates.append('tax_number')
        if updates:
            branch.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0008_branch_legal_name_branch_tax_number_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_branch_fiscal_profile, migrations.RunPython.noop),
    ]
