from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.platform.management.commands.check_database_role import unsafe_capabilities


class DatabaseRoleCheckTests(SimpleTestCase):
    def test_capability_mapping_is_fail_closed(self):
        self.assertEqual(unsafe_capabilities([False] * 11), [])
        self.assertEqual(
            unsafe_capabilities([True, False, False, False, True, False, True, True, False, False, False]),
            ['superuser', 'bypass row-level security', 'CREATE on the public schema', 'role memberships'],
        )

    @override_settings(DJANGO_PRODUCTION=True)
    @patch('apps.platform.management.commands.check_database_role.connection')
    def test_production_rejects_non_postgres_database(self, mocked_connection):
        mocked_connection.vendor = 'sqlite'
        with self.assertRaisesMessage(CommandError, 'must be PostgreSQL'):
            call_command('check_database_role', stdout=StringIO())

    @patch('apps.platform.management.commands.check_database_role.connection')
    def test_postgres_superuser_is_rejected(self, mocked_connection):
        mocked_connection.vendor = 'postgresql'
        cursor = MagicMock()
        cursor.fetchone.return_value = (
            'cafe_postcode', True, True, True, True, True, True, True, True, True, True, True
        )
        mocked_connection.cursor.return_value.__enter__.return_value = cursor

        with self.assertRaisesMessage(CommandError, 'Unsafe runtime database role'):
            call_command('check_database_role', stdout=StringIO())

    @patch('apps.platform.management.commands.check_database_role.connection')
    def test_least_privilege_postgres_role_is_accepted(self, mocked_connection):
        mocked_connection.vendor = 'postgresql'
        cursor = MagicMock()
        cursor.fetchone.return_value = (
            'cafe_postcode_app',
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        mocked_connection.cursor.return_value.__enter__.return_value = cursor
        output = StringIO()

        call_command('check_database_role', stdout=output)

        self.assertIn('is least-privilege', output.getvalue())
