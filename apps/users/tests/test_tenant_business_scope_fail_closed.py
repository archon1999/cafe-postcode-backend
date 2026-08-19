from uuid import uuid4

from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, APITestCase

from apps.catalog.models import CatalogCategory, CatalogItem, ModifierGroup
from apps.catalog.serializers import (
    CatalogCategorySerializer,
    CatalogItemGroupSerializer,
    CatalogItemSerializer,
)
from apps.floor.api.admin.serializers import (
    DiningTableSerializer,
    HallSerializer,
    TableSessionSerializer,
)
from apps.floor.models import DiningTable, Hall, ZoneOrCabin
from apps.integrations.models import IntegrationConfig
from apps.restaurants.api.admin.serializers import (
    CashDeskSerializer,
    DistributionPointSerializer,
    PrepStationSerializer,
)
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation, Restaurant
from apps.sales.serializers import OrderItemSerializer, OrderSerializer
from apps.users.models import Permission, Role, User


class TenantBusinessScopeFailClosedTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_restaurant = Restaurant.objects.create(name="First protected branch")
        cls.second_restaurant = Restaurant.objects.create(name="Second protected branch")

        cls.first_zone = ZoneOrCabin.objects.create(
            restaurant=cls.first_restaurant,
            name="First zone",
        )
        cls.second_zone = ZoneOrCabin.objects.create(
            restaurant=cls.second_restaurant,
            name="Second zone",
        )
        cls.first_hall = Hall.objects.create(
            zone_or_cabin=cls.first_zone,
            name="First hall",
        )
        cls.second_hall = Hall.objects.create(
            zone_or_cabin=cls.second_zone,
            name="Second hall",
        )
        cls.first_table = DiningTable.objects.create(
            hall=cls.first_hall,
            zone=cls.first_zone,
            name="First table",
            table_number=1,
        )
        cls.first_prep_station = PrepStation.objects.create(
            restaurant=cls.first_restaurant,
            name="First kitchen",
        )
        cls.first_category = CatalogCategory.objects.create(
            restaurant=cls.first_restaurant,
            name="First category",
            prep_station=cls.first_prep_station,
        )
        cls.first_item = CatalogItem.objects.create(
            restaurant=cls.first_restaurant,
            category=cls.first_category,
            name="First item",
            price=10_000,
        )
        cls.first_modifier_group = ModifierGroup.objects.create(
            restaurant=cls.first_restaurant,
            name="First modifier group",
        )
        cls.first_printer = IntegrationConfig.objects.create(
            restaurant=cls.first_restaurant,
            name="First printer",
            kind=IntegrationConfig.Kind.PRINTER,
            provider="windows-raw",
            is_enabled=True,
        )
        cls.first_cash_desk = CashDesk.objects.create(
            restaurant=cls.first_restaurant,
            name="First cash desk",
            printer_integration=cls.first_printer,
        )
        cls.first_distribution_point = DistributionPoint.objects.create(
            restaurant=cls.first_restaurant,
            name="First distribution point",
            kind=DistributionPoint.Kind.HALL,
            assigned_hall=cls.first_hall,
        )

        cls.employee_role = Role.objects.create(
            code="no-scope-employee-role",
            name="No-scope employee role",
            is_system=False,
        )
        cls.employee = User.objects.create_user(
            username="protected-employee",
            password="secret123",
            full_name="Protected Employee",
            restaurant=cls.first_restaurant,
            role=cls.employee_role,
        )

        cls.overprivileged_role = Role.objects.create(
            code="no-tenant-overprivileged",
            name="No-tenant overprivileged",
            is_system=False,
        )
        cls.overprivileged_role.permissions.set(Permission.objects.all())
        cls.no_tenant_user = User.objects.create_user(
            username="no-tenant-overprivileged",
            password="secret123",
            full_name="No Tenant Overprivileged",
            role=cls.overprivileged_role,
            is_staff=True,
        )

    def setUp(self):
        self.client.force_authenticate(self.no_tenant_user)

    @staticmethod
    def _queryset_for(field):
        return getattr(field, "child_relation", field).queryset

    def _request(self, path):
        request = Request(APIRequestFactory().post(path, {}, format="json"))
        request.user = self.no_tenant_user
        return request

    def test_all_business_relation_querysets_are_empty_without_tenant_scope(self):
        serializer_fields = (
            (
                HallSerializer(context={"request": self._request("/api/v1/admin/floor/halls/")}),
                ("zone_or_cabin_id",),
            ),
            (
                DiningTableSerializer(context={"request": self._request("/api/v1/admin/floor/tables/")}),
                ("hall", "zone"),
            ),
            (
                TableSessionSerializer(context={"request": self._request("/api/v1/admin/floor/table-sessions/")}),
                ("table", "assigned_waiter"),
            ),
            (
                CatalogCategorySerializer(context={"request": self._request("/api/v1/admin/catalog/categories/")}),
                ("prep_station",),
            ),
            (
                CatalogItemSerializer(context={"request": self._request("/api/v1/admin/catalog/items/")}),
                ("category", "prep_station", "modifier_groups"),
            ),
            (
                CashDeskSerializer(context={"request": self._request("/api/v1/admin/restaurants/cash-desks/")}),
                ("fiscal_integration", "payment_integration", "printer_integration"),
            ),
            (
                PrepStationSerializer(context={"request": self._request("/api/v1/admin/restaurants/prep-stations/")}),
                ("printer_integration", "cook_ids"),
            ),
            (
                DistributionPointSerializer(context={"request": self._request("/api/v1/admin/restaurants/distribution-points/")}),
                ("assigned_hall",),
            ),
            (
                OrderSerializer(context={"request": self._request("/api/v1/pos/sales/orders/")}),
                ("table_session", "distribution_point"),
            ),
            (
                OrderItemSerializer(context={"request": self._request("/api/v1/pos/sales/orders/items/")}),
                ("catalog_item",),
            ),
        )

        for serializer, field_names in serializer_fields:
            for field_name in field_names:
                with self.subTest(
                    serializer=serializer.__class__.__name__,
                    field=field_name,
                ):
                    self.assertFalse(
                        self._queryset_for(serializer.fields[field_name]).exists()
                    )

        item_group = CatalogItemGroupSerializer(
            context={
                "request": self._request("/api/v1/admin/catalog/item-groups/")
            }
        )
        self.assertFalse(item_group.fields["category"].queryset.exists())
        self.assertFalse(
            item_group.fields["members"]
            .child.fields["catalog_item"]
            .queryset.exists()
        )

    def test_business_lists_and_details_do_not_fall_back_to_another_tenant(self):
        for path in (
            "/api/v1/admin/catalog/categories/",
            "/api/v1/admin/catalog/items/",
            "/api/v1/admin/catalog/item-groups/",
            "/api/v1/admin/floor/zones/",
            "/api/v1/admin/floor/halls/",
            "/api/v1/admin/floor/tables/",
            "/api/v1/admin/restaurants/cash-desks/",
            "/api/v1/admin/restaurants/prep-stations/",
            "/api/v1/admin/restaurants/distribution-points/",
            "/api/v1/admin/employees/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                payload = (
                    response.data.get("data", response.data)
                    if hasattr(response.data, "get")
                    else response.data
                )
                self.assertEqual(payload, [])

        for actual_path, unknown_path in (
            (
                f"/api/v1/admin/catalog/categories/{self.first_category.id}/",
                f"/api/v1/admin/catalog/categories/{uuid4()}/",
            ),
            (
                f"/api/v1/admin/floor/halls/{self.first_hall.id}/",
                f"/api/v1/admin/floor/halls/{uuid4()}/",
            ),
            (
                f"/api/v1/admin/restaurants/cash-desks/{self.first_cash_desk.id}/",
                f"/api/v1/admin/restaurants/cash-desks/{uuid4()}/",
            ),
            (
                f"/api/v1/admin/restaurants/distribution-points/{self.first_distribution_point.id}/",
                f"/api/v1/admin/restaurants/distribution-points/{uuid4()}/",
            ),
            (
                f"/api/v1/admin/employees/{self.employee.id}/",
                f"/api/v1/admin/employees/{uuid4()}/",
            ),
        ):
            with self.subTest(path=actual_path):
                actual = self.client.get(actual_path)
                unknown = self.client.get(unknown_path)
                self.assertEqual(actual.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(unknown.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(actual.data, unknown.data)

    def test_no_tenant_write_and_relation_probes_are_fail_closed(self):
        report_response = self.client.get("/api/v1/admin/reporting/summary/")
        self.assertEqual(
            report_response.status_code,
            status.HTTP_403_FORBIDDEN,
            report_response.data,
        )

        before_zone_count = ZoneOrCabin.objects.count()
        response = self.client.post(
            "/api/v1/admin/floor/zones/",
            {"name": "Must not be created", "isActive": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertEqual(ZoneOrCabin.objects.count(), before_zone_count)

        hall_payload = {
            "name": "Must not be created",
            "isActive": True,
        }
        existing_hall_probe = self.client.post(
            "/api/v1/admin/floor/halls/",
            {**hall_payload, "zoneOrCabinId": str(self.first_zone.id)},
            format="json",
        )
        unknown_hall_probe = self.client.post(
            "/api/v1/admin/floor/halls/",
            {**hall_payload, "zoneOrCabinId": str(uuid4())},
            format="json",
        )
        self.assertEqual(existing_hall_probe.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_hall_probe.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(existing_hall_probe.data, unknown_hall_probe.data)

        point_payload = {
            "name": "Must not be created",
            "kind": DistributionPoint.Kind.HALL,
            "isActive": True,
        }
        existing_point_probe = self.client.post(
            "/api/v1/admin/restaurants/distribution-points/",
            {**point_payload, "assignedHall": str(self.first_hall.id)},
            format="json",
        )
        unknown_point_probe = self.client.post(
            "/api/v1/admin/restaurants/distribution-points/",
            {**point_payload, "assignedHall": str(uuid4())},
            format="json",
        )
        self.assertEqual(existing_point_probe.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_point_probe.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(existing_point_probe.data, unknown_point_probe.data)
        self.assertFalse(
            Hall.objects.filter(name="Must not be created").exists()
            or DistributionPoint.objects.filter(name="Must not be created").exists()
        )
