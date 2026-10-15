from django.db import migrations


def repair_retained_salary_type_default(apps, schema_editor):
    """Keep retained pre-retirement columns compatible with current inserts.

    Fresh databases have no salary_type column after users.0006. Some existing
    databases retain the legacy compensation columns for data preservation;
    their old NOT NULL salary_type needs its original empty-string default.
    Only change missing default metadata; do not alter existing compensation.
    """
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'users_employeeprofile' AND column_name = 'salary_type'"
        )
        column = cursor.fetchone()
        if column is None or column[0] is not None:
            return
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        schema_editor.execute(
            'ALTER TABLE "users_employeeprofile" '
            'ALTER COLUMN "salary_type" SET DEFAULT \'\''
        )


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0006_remove_employeeprofile_base_amount_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_retained_salary_type_default, migrations.RunPython.noop),
    ]
