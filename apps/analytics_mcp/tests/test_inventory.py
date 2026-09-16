from django.test import TestCase, override_settings

from apps.analytics_mcp.policy import AnalyticsError
from apps.analytics_mcp.service import execute_report
from apps.inventory import services
from apps.inventory.models import InventoryItem, Supplier, Warehouse
from apps.users.models import Permission
from .test_analytics import SETTINGS, ReportingTests


@override_settings(**SETTINGS)
class InventoryMCPTests(TestCase):
    def setUp(self):
        ReportingTests.setUp(self)
        permissions = Permission.objects.filter(
            code__in=["admin.inventory.view", "admin.inventory.view_cost"]
        )
        self.user.role.permissions.add(*permissions)
        for branch in (self.root, self.branch):
            branch.entitlement.permissions.add(*permissions)
        self.warehouse = services.default_warehouse(self.root)
        self.warehouse.kind = Warehouse.Kind.RAW
        self.warehouse.save(update_fields=["kind", "updated_at"])
        self.item = InventoryItem.objects.create(
            restaurant=self.root,
            name="Chicken",
            kind=InventoryItem.Kind.RAW,
            base_unit="g",
            min_quantity=2000,
        )
        supplier = Supplier.objects.create(restaurant=self.root, name="Supplier")
        receipt = services.create_document(
            self.root,
            {
                "kind": "receipt",
                "warehouse": str(self.warehouse.pk),
                "supplier": str(supplier.pk),
                "reference": "MCP-REC-1",
                "responsible_name": "Owner",
                "occurred_at": self.order.closed_at,
                "lines": [{"item": str(self.item.pk), "quantity": "1000", "unit_cost": "8"}],
            },
            self.user,
        )
        services.post_document(receipt, self.user)

    def test_inventory_summary_is_tenant_scoped_and_evidence_based(self):
        InventoryItem.objects.create(
            restaurant=self.root,
            name="Sunflower oil",
            kind=InventoryItem.Kind.RAW,
            base_unit="ml",
            min_quantity=500,
        )
        data = execute_report(self.principal, "get_inventory_summary", {"limit": 10})["data"]
        self.assertEqual(data["low_stock_count"], 2)
        alerts = {row["item"]: row for row in data["alerts"]}
        self.assertEqual(alerts["Chicken"]["quantity"], "1000.000000")
        self.assertEqual(alerts["Sunflower oil"]["quantity"], "0")
        with self.assertRaises(AnalyticsError):
            execute_report(
                self.principal,
                "get_inventory_summary",
                {"branch_ids": [str(self.foreign.pk)]},
            )

    def test_production_yield_and_recipe_cost_are_available_to_chatgpt(self):
        production = Warehouse.objects.create(
            restaurant=self.root, name="Kitchen", kind=Warehouse.Kind.PRODUCTION
        )
        transfer = services.create_document(
            self.root,
            {
                "kind": "transfer",
                "warehouse": str(self.warehouse.pk),
                "destination_warehouse": str(production.pk),
                "reference": "MCP-TR-1",
                "responsible_name": "Owner",
                "occurred_at": self.order.closed_at,
                "lines": [{"item": str(self.item.pk), "quantity": "1000"}],
            },
            self.user,
        )
        services.post_document(transfer, self.user)
        patty = InventoryItem.objects.create(
            restaurant=self.root,
            name="Chicken Patty",
            kind=InventoryItem.Kind.SEMI_FINISHED,
            base_unit="piece",
        )
        recipe = services.create_recipe(
            self.root,
            {
                "output_item": str(patty.pk),
                "yield_quantity": "1",
                "lines": [{"item": str(self.item.pk), "quantity": "100"}],
            },
            self.user,
        )
        batch = services.create_document(
            self.root,
            {
                "kind": "production",
                "warehouse": str(production.pk),
                "production_recipe": str(recipe.pk),
                "planned_quantity": "10",
                "actual_quantity": "8",
                "reference": "MCP-PR-1",
                "responsible_name": "Chef",
                "occurred_at": self.order.closed_at,
            },
            self.user,
        )
        services.post_document(batch, self.user)
        yield_data = execute_report(self.principal, "get_production_yield", self.args)["data"]
        self.assertEqual(yield_data["batches"][0]["yield_percent"], "80.0")
        cost_data = execute_report(self.principal, "get_recipe_costs", {"limit": 10})["data"]
        self.assertEqual(cost_data["recipes"][0]["name"], "Chicken Patty")

    def test_inventory_tool_rechecks_mutable_permission(self):
        permission = Permission.objects.get(code="admin.inventory.view")
        self.user.role.permissions.remove(permission)
        with self.assertRaises(AnalyticsError):
            execute_report(self.principal, "get_inventory_summary", {})
