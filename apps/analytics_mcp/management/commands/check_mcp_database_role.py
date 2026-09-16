from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Require a dedicated MCP role with no business-table write or role-administration rights."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("This check requires PostgreSQL.")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            if any(cursor.fetchone()):
                raise CommandError(
                    "MCP must use an unprivileged dedicated database role."
                )
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename ~ '^(sales_|billing_|catalog_|floor_|inventory_|restaurants_|platform_)' AND has_table_privilege(current_user,quote_ident(tablename),'INSERT,UPDATE,DELETE,TRUNCATE')"
            )
            if cursor.fetchall():
                raise CommandError("MCP role has business-table write privileges.")
            cursor.execute(
                "SELECT has_table_privilege(current_user,'analytics_mcp_reportsnapshot','INSERT'),has_table_privilege(current_user,'sales_order','SELECT')"
            )
            if not all(cursor.fetchone()):
                raise CommandError("Required analytics privileges are missing.")
        self.stdout.write("MCP database isolation: passed")
