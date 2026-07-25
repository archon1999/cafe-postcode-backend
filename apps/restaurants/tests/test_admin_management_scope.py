from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import CashDesk, PrepStation, Restaurant
from apps.users.models import User


class AdminManagementScopeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.first_restaurant = Restaurant.objects.create(name="First branch")
        self.second_restaurant = Restaurant.objects.create(name="Second branch")
        self.superuser = User.objects.create_superuser(
            username="management-scope-superuser",
            password="secret123",
            full_name="Management Scope Superuser",
        )
        self.client.force_authenticate(self.superuser)

        CashDesk.objects.create(
            restaurant=self.first_restaurant, name="First cash desk"
        )
        CashDesk.objects.create(
            restaurant=self.second_restaurant, name="Second cash desk"
        )
        PrepStation.objects.create(
            restaurant=self.first_restaurant, name="First kitchen"
        )
        PrepStation.objects.create(
            restaurant=self.second_restaurant, name="Second kitchen"
        )
        IntegrationConfig.objects.create(
            restaurant=self.first_restaurant,
            name="First printer",
            kind=IntegrationConfig.Kind.PRINTER,
            provider="windows-raw",
        )
        IntegrationConfig.objects.create(
            restaurant=self.second_restaurant,
            name="Second printer",
            kind=IntegrationConfig.Kind.PRINTER,
            provider="windows-raw",
        )

    def test_management_lists_without_header_include_all_branches(self):
        for path in (
            "/api/v1/admin/restaurants/cash-desks/",
            "/api/v1/admin/restaurants/prep-stations/",
            "/api/v1/admin/integrations/configs/",
        ):
            response = self.client.get(path)

            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(
                {item["restaurant_name"] for item in response.data["data"]},
                {self.first_restaurant.name, self.second_restaurant.name},
            )

    def test_management_lists_with_header_filter_to_selected_branch(self):
        self.client.credentials(
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.second_restaurant.id)
        )

        for path in (
            "/api/v1/admin/restaurants/cash-desks/",
            "/api/v1/admin/restaurants/prep-stations/",
            "/api/v1/admin/integrations/configs/",
        ):
            response = self.client.get(path)

            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            self.assertEqual(
                [item["restaurant_name"] for item in response.data["data"]],
                [self.second_restaurant.name],
            )
