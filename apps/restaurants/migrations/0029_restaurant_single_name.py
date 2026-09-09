from django.db import migrations


def preserve_names(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    alias = schema_editor.connection.alias
    for restaurant in Restaurant.objects.using(alias).all().iterator():
        changes = {}
        for field in ('name', 'legal_name'):
            # The original column holds the last saved business name. Only
            # fall back to a translation when that canonical value is empty.
            if not (getattr(restaurant, field) or '').strip():
                for suffix in ('_uz', '_ru', '_uz_crl'):
                    value = getattr(restaurant, field + suffix)
                    if value and value.strip():
                        changes[field] = value
                        break
        if changes:
            Restaurant.objects.using(alias).filter(pk=restaurant.pk).update(**changes)


class Migration(migrations.Migration):
    dependencies = [('restaurants', '0028_restore_auth_code_rollback_column')]
    operations = [
        migrations.RunPython(preserve_names, migrations.RunPython.noop),
        # Retain historical translations physically for rollback/audit; the
        # application no longer reads or writes language-specific names.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name='restaurant', name=field + suffix)
                for field in ('name', 'legal_name')
                for suffix in ('_uz', '_uz_crl', '_ru')
            ],
        ),
    ]
