from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory
from apps.restaurants.models import PrepStation, Restaurant
from apps.platform.models import RestaurantEntitlement


class AdminScopeHeaderTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.second_restaurant = Restaurant.objects.create(name='Restaurant Two')
        cls.permission = Permission.objects.get_or_create(
            code='catalog_categories.create',
            defaults={'name': 'Catalog category create', 'description': 'Catalog category create permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='catalog-admin',
            defaults={'name': 'Catalog admin', 'description': 'Catalog admin role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set([cls.permission])
        cls.entitlement.allowed_roles.set([cls.role])
        cls.admin_user = User.objects.create_user(
            username='catalog-admin',
            password='secret123',
            full_name='Catalog Admin',
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            username='scope-superuser',
            password='secret123',
            full_name='Scope Superuser',
        )
        cls.chef_role = Role.objects.get_or_create(
            code='chef',
            defaults={'name': 'Chef', 'description': 'Chef role', 'is_system': True},
        )[0]

    def create_payload(self):
        return {
            'name': 'Scoped category',
            'name_uz': 'Scoped category',
            'name_uz_crl': 'Scoped category',
            'name_ru': 'Scoped category',
            'mxik_code': '10000000000000001',
            'mxik_name': 'Scoped category',
            'kind': 'dish',
            'sort_order': 1,
            'is_active': True,
        }

    def test_superuser_admin_post_requires_restaurant_header(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post('/api/v1/admin/catalog/categories/', self.create_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('restaurantId', response.data)

    def test_superuser_admin_post_accepts_valid_restaurant_header(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            '/api/v1/admin/catalog/categories/',
            self.create_payload(),
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CatalogCategory.objects.filter(pk=response.data['id'], restaurant=self.restaurant).exists())

    def test_regular_admin_uses_own_scope_without_headers(self):
        self.client.force_authenticate(self.admin_user)

        response = self.client.post('/api/v1/admin/catalog/categories/', self.create_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CatalogCategory.objects.filter(pk=response.data['id'], restaurant=self.restaurant).exists())

    def test_prep_station_drops_foreign_cook_ids_for_selected_restaurant(self):
        self.client.force_authenticate(self.superuser)
        foreign_cook = User.objects.create_user(
            username='foreign-chef',
            password='secret123',
            full_name='Foreign Chef',
            restaurant=self.second_restaurant,
            role=self.chef_role,
        )

        response = self.client.post(
            '/api/v1/admin/restaurants/prep-stations/',
            {
                'name': 'Kitchen',
                'kind': 'kitchen',
                'printer_integration': None,
                'cook_ids': [str(foreign_cook.id)],
                'is_active': True,
            },
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        station = PrepStation.objects.get(pk=response.data['id'])
        self.assertEqual(station.restaurant, self.restaurant)
        self.assertEqual(station.cooks.count(), 0)

    def test_prep_station_accepts_cook_from_selected_restaurant(self):
        self.client.force_authenticate(self.superuser)
        cook = User.objects.create_user(
            username='own-chef',
            password='secret123',
            full_name='Own Chef',
            restaurant=self.restaurant,
            role=self.chef_role,
        )

        response = self.client.post(
            '/api/v1/admin/restaurants/prep-stations/',
            {
                'name': 'Kitchen',
                'kind': 'kitchen',
                'printer_integration': None,
                'cook_ids': [str(cook.id)],
                'is_active': True,
            },
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        station = PrepStation.objects.get(pk=response.data['id'])
        self.assertEqual(list(station.cooks.values_list('id', flat=True)), [cook.id])

