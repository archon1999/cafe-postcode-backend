from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, User


class AdminPermissionOptionsApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='permissions-options-admin',
            password='secret123',
            full_name='Permissions Options Admin',
        )
        cls.permissions = [
            Permission.objects.get_or_create(
                code=code,
                defaults={'name': code, 'description': f'{code} permission'},
            )[0]
            for code in ('users.list', 'users.create', 'roles.list')
        ]

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin_user)

    def test_admin_permissions_options_returns_unpaginated_permissions(self):
        response = self.client.get('/api/v1/admin/users/permissions/options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsInstance(response.data, list)

        response_codes = {item['code'] for item in response.data}
        self.assertTrue({'users.list', 'users.create', 'roles.list'}.issubset(response_codes))
        self.assertSetEqual(
            set(response.data[0].keys()),
            {'id', 'code', 'scope', 'name', 'description'},
        )
