from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.organizations.models import Branch, Restaurant, RestaurantEntitlement


class AdminScopeHeaderTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.branch = Branch.objects.create(restaurant=cls.restaurant, name='Main', is_default=True)
        cls.second_restaurant = Restaurant.objects.create(name='Restaurant Two')
        cls.second_branch = Branch.objects.create(
            restaurant=cls.second_restaurant,
            name='Second',
            is_default=True,
        )
        cls.permission = Permission.objects.get_or_create(
            code='catalog.manage',
            defaults={'name': 'Catalog manage', 'description': 'Catalog manage permission'},
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
            branch=cls.branch,
            role=cls.role,
            actor_type=User.ActorType.RESTAURANT_ADMIN,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            username='scope-superuser',
            password='secret123',
            full_name='Scope Superuser',
        )

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

    def test_superuser_admin_post_requires_restaurant_and_branch_headers(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post('/api/v1/admin/catalog/categories/', self.create_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('restaurantId', response.data)

    def test_superuser_admin_post_rejects_mismatched_branch_header(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            '/api/v1/admin/catalog/categories/',
            self.create_payload(),
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
            HTTP_X_ADMIN_BRANCH_ID=str(self.second_branch.id),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('branchId', response.data)

    def test_superuser_admin_post_accepts_valid_scope_headers(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            '/api/v1/admin/catalog/categories/',
            self.create_payload(),
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
            HTTP_X_ADMIN_BRANCH_ID=str(self.branch.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data['branch']), str(self.branch.id))

    def test_regular_admin_uses_own_scope_without_headers(self):
        self.client.force_authenticate(self.admin_user)

        response = self.client.post('/api/v1/admin/catalog/categories/', self.create_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data['branch']), str(self.branch.id))
