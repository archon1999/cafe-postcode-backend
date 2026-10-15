from importlib import import_module
from unittest import skipUnless

from django.apps import apps
from django.db import connection, IntegrityError, transaction
from django.test import TestCase

from apps.users.models import User


repair = import_module(
    'apps.users.migrations.0007_retained_salary_type_insert_default'
).repair_retained_salary_type_default


@skipUnless(connection.vendor == 'postgresql', 'Retained-column repair targets PostgreSQL')
class RetainedSalaryTypeDefaultTests(TestCase):
    def repair(self):
        with connection.schema_editor() as editor:
            repair(apps, editor)

    def test_fresh_database_without_legacy_column_still_creates_profiles(self):
        self.repair()
        user = User.objects.create_user(username='fresh-profile', full_name='Fresh')
        self.assertEqual(user.employee_profile.employment_status, 'active')

    def test_retained_required_column_gets_default_without_changing_legacy_data(self):
        existing = User.objects.create_user(username='existing-profile', full_name='Existing')
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute(
                "ALTER TABLE users_employeeprofile ADD COLUMN salary_type varchar(16) "
                "NOT NULL DEFAULT 'monthly'"
            )
            cursor.execute('ALTER TABLE users_employeeprofile ALTER COLUMN salary_type DROP DEFAULT')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='blocked-profile', full_name='Blocked')

        self.repair()
        self.repair()  # Repeated repair leaves both data and the default intact.
        created = User.objects.create_user(username='repaired-profile', full_name='Repaired')

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT user_id, salary_type FROM users_employeeprofile WHERE user_id IN (%s, %s)',
                [existing.pk, created.pk],
            )
            values = dict(cursor.fetchall())
        self.assertEqual(values[existing.pk], 'monthly')
        self.assertEqual(values[created.pk], '')
        self.assertFalse(User.objects.filter(username='blocked-profile').exists())

    def test_existing_database_default_is_preserved(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE users_employeeprofile ADD COLUMN salary_type varchar(16) "
                "NOT NULL DEFAULT 'daily'"
            )
        self.repair()
        created = User.objects.create_user(username='existing-default', full_name='Existing default')
        with connection.cursor() as cursor:
            cursor.execute('SELECT salary_type FROM users_employeeprofile WHERE user_id = %s', [created.pk])
            self.assertEqual(cursor.fetchone()[0], 'daily')
