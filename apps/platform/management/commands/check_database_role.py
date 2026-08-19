from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


ROLE_ATTRIBUTE_NAMES = (
    'superuser',
    'create roles',
    'create databases',
    'replication',
    'bypass row-level security',
    'database ownership',
    'CREATE on the public schema',
    'role memberships',
    'database object ownership',
    'unsafe table privileges',
    'EXECUTE on public-schema functions',
)


def unsafe_capabilities(values):
    return [name for name, enabled in zip(ROLE_ATTRIBUTE_NAMES, values, strict=True) if enabled]


class Command(BaseCommand):
    help = 'Fail unless the configured runtime PostgreSQL role is least-privilege.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            if getattr(settings, 'DJANGO_PRODUCTION', False):
                raise CommandError('The production runtime database must be PostgreSQL.')
            self.stdout.write(self.style.WARNING('Database role check skipped outside PostgreSQL.'))
            return

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_user,
                    role.rolsuper,
                    role.rolcreaterole,
                    role.rolcreatedb,
                    role.rolreplication,
                    role.rolbypassrls,
                    database.datdba = role.oid,
                    has_schema_privilege(current_user, 'public', 'CREATE'),
                    EXISTS (
                        SELECT 1 FROM pg_auth_members AS membership
                        WHERE membership.member = role.oid
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                        WHERE relation.relowner = role.oid
                          AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
                    ) OR EXISTS (
                        SELECT 1 FROM pg_namespace AS namespace
                        WHERE namespace.nspowner = role.oid
                          AND namespace.nspname NOT LIKE 'pg_%'
                          AND namespace.nspname != 'information_schema'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                          AND (
                              has_table_privilege(current_user, relation.oid, 'TRUNCATE')
                              OR has_table_privilege(current_user, relation.oid, 'REFERENCES')
                              OR has_table_privilege(current_user, relation.oid, 'TRIGGER')
                          )
                    ),
                    EXISTS (
                        SELECT 1
                        FROM pg_proc AS function
                        JOIN pg_namespace AS namespace ON namespace.oid = function.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND has_function_privilege(current_user, function.oid, 'EXECUTE')
                    )
                FROM pg_roles AS role
                JOIN pg_database AS database ON database.datname = current_database()
                WHERE role.rolname = current_user
                """
            )
            row = cursor.fetchone()

        if row is None:
            raise CommandError('The current PostgreSQL role could not be inspected.')
        role_name, *capabilities = row
        unsafe = unsafe_capabilities(capabilities)
        if unsafe:
            raise CommandError(f'Unsafe runtime database role {role_name!r}: {", ".join(unsafe)}.')
        self.stdout.write(self.style.SUCCESS(f'Runtime database role {role_name!r} is least-privilege.'))
