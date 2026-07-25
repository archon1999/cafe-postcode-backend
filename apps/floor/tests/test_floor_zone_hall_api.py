from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.floor.models import DiningTable, Hall, ZoneOrCabin
from apps.restaurants.models import Restaurant


class AdminFloorZoneHallApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.restaurant = Restaurant.objects.create(name="Floor API restaurant")
        self.other_restaurant = Restaurant.objects.create(name="Other restaurant")
        self.superuser = User.objects.create_superuser(
            username="floor-superuser",
            password="secret123",
            full_name="Floor Superuser",
        )
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_zone_catalog_and_hall_assignment_flow(self):
        zone_response = self.client.post(
            "/api/v1/admin/floor/zones/",
            {
                "name": "VIP kabina",
                "sortOrder": 1,
                "isActive": True,
            },
            format="json",
        )

        self.assertEqual(zone_response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("hall", zone_response.data)
        self.assertNotIn("isPrivate", zone_response.data)

        hall_response = self.client.post(
            "/api/v1/admin/floor/halls/",
            {
                "name": "Asosiy zal",
                "description": "Main hall",
                "gridColumns": 8,
                "sortOrder": 2,
                "isActive": True,
                "zoneOrCabinId": zone_response.data["id"],
            },
            format="json",
        )

        self.assertEqual(hall_response.status_code, status.HTTP_201_CREATED)
        zone_or_cabin = hall_response.data.get("zoneOrCabin") or hall_response.data.get(
            "zone_or_cabin"
        )
        zone_or_cabin_id = hall_response.data.get(
            "zoneOrCabinId"
        ) or hall_response.data.get("zone_or_cabin_id")
        self.assertIsNotNone(zone_or_cabin)
        self.assertEqual(str(zone_or_cabin["id"]), str(zone_response.data["id"]))
        self.assertEqual(str(zone_or_cabin_id), str(zone_response.data["id"]))

        zone_detail_response = self.client.get(
            f"/api/v1/admin/floor/zones/{zone_response.data['id']}/"
        )
        self.assertEqual(zone_detail_response.status_code, status.HTTP_200_OK)
        self.assertNotIn("hall", zone_detail_response.data)

    def test_hall_and_zone_lists_default_to_sort_order(self):
        zone_b = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="B zona", sort_order=2, is_active=True
        )
        zone_a = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="A zona", sort_order=1, is_active=True
        )

        Hall.objects.create(
            zone_or_cabin=zone_b, name="B zal", sort_order=2, is_active=True
        )
        Hall.objects.create(
            zone_or_cabin=zone_a, name="A zal", sort_order=1, is_active=True
        )

        halls_response = self.client.get("/api/v1/admin/floor/halls/")
        zones_response = self.client.get("/api/v1/admin/floor/zones/")

        self.assertEqual(
            [row["name"] for row in halls_response.data["data"]], ["A zal", "B zal"]
        )
        self.assertEqual(
            [row["name"] for row in zones_response.data["data"]], ["A zona", "B zona"]
        )

    def test_superuser_without_header_can_read_all_branch_floor_resources(self):
        local_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="Local zone", sort_order=1
        )
        other_zone = ZoneOrCabin.objects.create(
            restaurant=self.other_restaurant, name="Other zone", sort_order=1
        )
        local_hall = Hall.objects.create(zone_or_cabin=local_zone, name="Local hall")
        other_hall = Hall.objects.create(zone_or_cabin=other_zone, name="Other hall")
        DiningTable.objects.create(
            hall=local_hall, zone=local_zone, name="Local table", table_number=1
        )
        other_table = DiningTable.objects.create(
            hall=other_hall, zone=other_zone, name="Other table", table_number=1
        )
        self.client.credentials()

        zones_response = self.client.get("/api/v1/admin/floor/zones/")
        halls_response = self.client.get("/api/v1/admin/floor/halls/")
        tables_response = self.client.get("/api/v1/admin/floor/tables/")
        zone_detail_response = self.client.get(
            f"/api/v1/admin/floor/zones/{other_zone.id}/"
        )
        hall_detail_response = self.client.get(
            f"/api/v1/admin/floor/halls/{other_hall.id}/"
        )
        table_detail_response = self.client.get(
            f"/api/v1/admin/floor/tables/{other_table.id}/"
        )

        for response in (
            zones_response,
            halls_response,
            tables_response,
            zone_detail_response,
            hall_detail_response,
            table_detail_response,
        ):
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            {row["restaurant_name"] for row in zones_response.data["data"]},
            {self.restaurant.name, self.other_restaurant.name},
        )
        self.assertEqual(
            {row["restaurant_name"] for row in halls_response.data["data"]},
            {self.restaurant.name, self.other_restaurant.name},
        )
        self.assertEqual(
            {row["restaurant_name"] for row in tables_response.data["data"]},
            {self.restaurant.name, self.other_restaurant.name},
        )

    def test_halls_and_zones_append_reorder_and_delete(self):
        first_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name="First zone",
            sort_order=3,
            is_active=True,
        )
        zone_response = self.client.post(
            "/api/v1/admin/floor/zones/",
            {"name": "Appended zone", "isActive": True},
            format="json",
        )
        self.assertEqual(
            zone_response.status_code, status.HTTP_201_CREATED, zone_response.data
        )
        self.assertEqual(zone_response.data["sort_order"], 4)

        first_hall = Hall.objects.create(
            zone_or_cabin=first_zone,
            name="First hall",
            sort_order=2,
            is_active=True,
        )
        hall_response = self.client.post(
            "/api/v1/admin/floor/halls/",
            {
                "name": "Appended hall",
                "description": "",
                "isActive": True,
                "zoneOrCabinId": str(first_zone.id),
            },
            format="json",
        )
        self.assertEqual(
            hall_response.status_code, status.HTTP_201_CREATED, hall_response.data
        )
        self.assertEqual(hall_response.data["sort_order"], 3)

        reorder_response = self.client.patch(
            f"/api/v1/admin/floor/halls/{hall_response.data['id']}/",
            {"sortOrder": 0},
            format="json",
        )
        self.assertEqual(
            reorder_response.status_code, status.HTTP_200_OK, reorder_response.data
        )
        self.assertEqual(reorder_response.data["sort_order"], 0)

        delete_hall_response = self.client.delete(
            f"/api/v1/admin/floor/halls/{first_hall.id}/"
        )
        self.assertEqual(delete_hall_response.status_code, status.HTTP_204_NO_CONTENT)

        protected_zone_response = self.client.delete(
            f"/api/v1/admin/floor/zones/{first_zone.id}/"
        )
        self.assertEqual(
            protected_zone_response.status_code, status.HTTP_400_BAD_REQUEST
        )

        delete_zone_response = self.client.delete(
            f"/api/v1/admin/floor/zones/{zone_response.data['id']}/"
        )
        self.assertEqual(delete_zone_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_table_create_uses_hall_zone_as_source_of_truth(self):
        zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name="Assigned zone",
            sort_order=1,
            is_active=True,
        )
        detached_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name="Detached zone",
            sort_order=2,
            is_active=True,
        )
        hall = Hall.objects.create(
            zone_or_cabin=zone, name="Hall", sort_order=1, is_active=True
        )

        response = self.client.post(
            "/api/v1/admin/floor/tables/",
            {
                "hall": str(hall.id),
                "zone": str(detached_zone.id),
                "name": "1-stol",
                "tableNumber": 1,
                "seatCount": 4,
                "shapeVariant": "seat4_square",
                "status": "available",
                "positionX": 0,
                "positionY": 0,
                "width": 1,
                "height": 1,
                "rotation": 0,
                "isActive": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        table = DiningTable.objects.get(pk=response.data["id"])
        self.assertEqual(table.zone_id, zone.id)
        self.assertEqual(str(response.data["zone"]), str(zone.id))

    def test_hall_update_rejects_zone_from_other_restaurant(self):
        zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="Local zone", sort_order=1, is_active=True
        )
        other_zone = ZoneOrCabin.objects.create(
            restaurant=self.other_restaurant,
            name="Foreign zone",
            sort_order=1,
            is_active=True,
        )
        hall = Hall.objects.create(
            zone_or_cabin=zone,
            name="Occupied hall",
            description="Hall with zone",
            grid_columns=8,
            sort_order=1,
            is_active=True,
        )

        response = self.client.put(
            f"/api/v1/admin/floor/halls/{hall.id}/",
            {
                "name": hall.name,
                "description": hall.description,
                "gridColumns": hall.grid_columns,
                "sortOrder": hall.sort_order,
                "isActive": hall.is_active,
                "zoneOrCabinId": str(other_zone.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("zoneOrCabinId", response.data)

    def test_hall_update_rejects_changing_zone_while_tables_exist(self):
        zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="Busy zone", sort_order=1, is_active=True
        )
        replacement_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name="Replacement zone",
            sort_order=2,
            is_active=True,
        )
        hall = Hall.objects.create(
            zone_or_cabin=zone,
            name="Occupied hall",
            description="Hall with table",
            grid_columns=8,
            sort_order=1,
            is_active=True,
        )
        DiningTable.objects.create(
            hall=hall,
            zone=zone,
            name="1-stol",
            table_number=1,
            seat_count=4,
            shape=DiningTable.Shape.SQUARE,
            shape_variant=DiningTable.ShapeVariant.SEAT4_SQUARE,
            status=DiningTable.Status.AVAILABLE,
            position_x=0,
            position_y=0,
            width=1,
            height=1,
        )

        response = self.client.put(
            f"/api/v1/admin/floor/halls/{hall.id}/",
            {
                "name": hall.name,
                "description": hall.description,
                "gridColumns": hall.grid_columns,
                "sortOrder": hall.sort_order,
                "isActive": hall.is_active,
                "zoneOrCabinId": str(replacement_zone.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("zoneOrCabinId", response.data)
