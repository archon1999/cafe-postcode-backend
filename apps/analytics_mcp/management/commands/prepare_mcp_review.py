"""Create a reserved, synthetic review tenant without modifying existing data."""

import os
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.billing.models import CashExpense, CashShift, ExpenseCategory, Payment
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import CashDesk, Restaurant
from apps.sales.models import Order, OrderItem
from apps.users.models import Permission, Role, User
from common.utils.date import TASHKENT_TIMEZONE

USERNAME = "mcp-openai-review"
TENANT_ID = uuid5(NAMESPACE_URL, "https://mcp.cafe-postcode.uz/review/synthetic-v1")
ROLE_CODE = "mcp-review-readonly"
PERMISSIONS = {"dashboard.view", "reports.view", "expenses.view"}


class Command(BaseCommand):
    help = "Prepare synthetic 7–13 September 2026 review data. Default: rollback; --commit persists."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("MCP_REVIEW_PASSWORD", "")
        if len(password) < 24:
            raise CommandError(
                "Set MCP_REVIEW_PASSWORD to a random secret of at least 24 characters."
            )
        # A repeated run must not reset passwords, add duplicate sales or touch a
        # tenant that an operator may have changed after initial preparation.
        if (
            Restaurant.objects.filter(pk=TENANT_ID).exists()
            or User.objects.filter(username=USERNAME).exists()
            or Role.objects.filter(code=ROLE_CODE).exists()
        ):
            raise CommandError(
                "Reserved review records already exist; no changes made."
            )
        permissions = list(Permission.objects.filter(code__in=PERMISSIONS))
        if {p.code for p in permissions} != PERMISSIONS:
            raise CommandError("Required read-only permissions are missing.")
        restaurant = Restaurant.objects.create(
            id=TENANT_ID, name="Cafe Postcode · Review (synthetic)", vat_enabled=False
        )
        role = Role.objects.create(code=ROLE_CODE, name="MCP review: read only")
        role.permissions.set(permissions)
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=restaurant, is_active=True
        )
        entitlement.permissions.set(permissions)
        entitlement.allowed_roles.add(role)
        user = User.objects.create_user(
            username=USERNAME,
            password=password,
            full_name="Demo operator",
            restaurant=restaurant,
            role=role,
        )
        desk = CashDesk.objects.create(restaurant=restaurant, name="Demo cash desk")
        category = CatalogCategory.objects.create(
            restaurant=restaurant, name="Demo menu"
        )
        products = [
            CatalogItem.objects.create(
                restaurant=restaurant, category=category, name=name, price=price
            )
            for name, price in [("Osh", 40000), ("Choy", 10000)]
        ]
        zone = ZoneOrCabin.objects.create(restaurant=restaurant, name="Demo hall")
        hall = Hall.objects.create(zone_or_cabin=zone, name="Demo hall")
        table = DiningTable.objects.create(hall=hall, name="1")
        expense_category = ExpenseCategory.objects.create(
            restaurant=restaurant, name="Transport"
        )
        start = datetime(2026, 9, 7, 12, tzinfo=TASHKENT_TIMEZONE)
        number = 0
        for day in range(7):
            at = start + timedelta(days=day)
            count = day + 1
            shift = CashShift.objects.create(
                cash_desk=desk,
                opened_by=user,
                closed_by=user,
                opened_at=at - timedelta(hours=3),
                closed_at=at + timedelta(hours=8),
                status=CashShift.Status.CLOSED,
                cash_total=50000 * count,
                expense_total=5000,
                receipt_count=count,
                expected_closing_cash_amount=50000 * count - 5000,
                actual_closing_cash_amount=50000 * count - 5000,
            )
            CashExpense.objects.create(
                restaurant=restaurant,
                cash_shift=shift,
                cash_desk=desk,
                category=expense_category,
                category_name_snapshot="Transport",
                created_by=user,
                occurred_at=at,
                amount=5000,
            )
            for _ in range(count):
                number += 1
                session = TableSession.objects.create(
                    restaurant=restaurant, hall=hall, table=table
                )
                order = Order.objects.create(
                    restaurant=restaurant,
                    order_number=number,
                    status=Order.Status.CLOSED,
                    total=50000,
                    closed_at=at,
                    table_session=session,
                )
                for product in products:
                    OrderItem.objects.create(
                        order=order,
                        catalog_item=product,
                        created_by=user,
                        quantity=1,
                        unit_price=product.price,
                        line_total=product.price,
                    )
                Payment.objects.create(
                    order=order,
                    cash_desk=desk,
                    cash_shift=shift,
                    received_by=user,
                    register_fiscal=False,
                    amount=50000,
                    method=Payment.Method.CASH,
                    status=Payment.Status.SUCCEEDED,
                    paid_at=at,
                )
        if not options["commit"]:
            transaction.set_rollback(True)
        self.stdout.write(
            f"{'Created' if options['commit'] else 'Validated and rolled back'} synthetic review tenant. "
            "2026-09-07..13: 28 orders, 1,400,000 UZS sales, 35,000 UZS expenses. "
            "Password was not logged."
        )
