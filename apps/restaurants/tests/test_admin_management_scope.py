from uuid import uuid4

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.floor.models import Hall, ZoneOrCabin
from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import (
    CashDesk,
    DistributionPoint,
    PrepStation,
    Restaurant,
)
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

        self.first_zone = ZoneOrCabin.objects.create(
            restaurant=self.first_restaurant,
            name='First zone',
        )
        self.second_zone = ZoneOrCabin.objects.create(
            restaurant=self.second_restaurant,
            name='Second zone',
        )
        self.first_hall = Hall.objects.create(
            zone_or_cabin=self.first_zone,
            name='First hall',
        )
        self.second_hall = Hall.objects.create(
            zone_or_cabin=self.second_zone,
            name='Second hall',
        )

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
        self.first_distribution_point = DistributionPoint.objects.create(
            restaurant=self.first_restaurant,
            name='First hall point',
            kind=DistributionPoint.Kind.HALL,
            assigned_hall=self.first_hall,
        )
        self.second_distribution_point = DistributionPoint.objects.create(
            restaurant=self.second_restaurant,
            name='Second hall point',
            kind=DistributionPoint.Kind.HALL,
            assigned_hall=self.second_hall,
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

    def test_distribution_point_lists_respect_selected_branch(self):
        all_branches_response = self.client.get(
            '/api/v1/admin/restaurants/distribution-points/'
        )
        self.assertEqual(
            all_branches_response.status_code,
            status.HTTP_200_OK,
            all_branches_response.data,
        )
        self.assertEqual(
            {row['id'] for row in all_branches_response.data['data']},
            {
                str(point_id)
                for point_id in DistributionPoint.objects.values_list(
                    'id',
                    flat=True,
                )
            },
        )

        self.client.credentials(
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.second_restaurant.id)
        )
        selected_branch_response = self.client.get(
            '/api/v1/admin/restaurants/distribution-points/'
        )
        self.assertEqual(
            selected_branch_response.status_code,
            status.HTTP_200_OK,
            selected_branch_response.data,
        )
        self.assertEqual(
            {row['id'] for row in selected_branch_response.data['data']},
            {
                str(point_id)
                for point_id in DistributionPoint.objects.filter(
                    restaurant=self.second_restaurant,
                ).values_list('id', flat=True)
            },
        )

    def test_distribution_point_rejects_foreign_and_unknown_hall_equally(self):
        self.client.credentials(
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.first_restaurant.id)
        )
        base_payload = {
            'name': 'Scoped distribution',
            'kind': DistributionPoint.Kind.HALL,
            'isActive': True,
        }

        foreign_response = self.client.post(
            '/api/v1/admin/restaurants/distribution-points/',
            {
                **base_payload,
                'assignedHall': str(self.second_hall.id),
            },
            format='json',
        )
        unknown_response = self.client.post(
            '/api/v1/admin/restaurants/distribution-points/',
            {
                **base_payload,
                'assignedHall': str(uuid4()),
            },
            format='json',
        )

        self.assertEqual(foreign_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign_response.data, unknown_response.data)
        self.assertFalse(
            DistributionPoint.objects.filter(
                restaurant=self.first_restaurant,
                name='Scoped distribution',
            ).exists()
        )

        local_response = self.client.post(
            '/api/v1/admin/restaurants/distribution-points/',
            {
                **base_payload,
                'assignedHall': str(self.first_hall.id),
            },
            format='json',
        )
        self.assertEqual(
            local_response.status_code,
            status.HTTP_201_CREATED,
            local_response.data,
        )
        created = DistributionPoint.objects.get(pk=local_response.data['id'])
        self.assertEqual(created.restaurant_id, self.first_restaurant.id)
        self.assertEqual(created.assigned_hall_id, self.first_hall.id)
