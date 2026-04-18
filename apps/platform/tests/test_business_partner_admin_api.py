from rest_framework import status
from rest_framework.test import APITestCase

from apps.platform.models import BusinessPartner
from apps.restaurants.models import Restaurant
from apps.users.models import Role, User


class BusinessPartnerAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product_owner_role = Role.objects.get(code='product_owner')
        cls.business_partner_role = Role.objects.get(code='business_partner')

        cls.product_owner_user = User.objects.create_user(
            username='platform-owner',
            password='secret123',
            full_name='Platform Owner',
            role=cls.product_owner_role,
            is_staff=True,
            is_active=True,
        )

        cls.partner = BusinessPartner.objects.create(
            inn='123456789',
            company_name='Partner LLC',
            legal_name='Partner LLC',
            director_name='Owner',
            phone='+998900000001',
            email='partner@example.com',
            address='Tashkent',
            status=BusinessPartner.Status.DRAFT,
        )
        cls.other_partner = BusinessPartner.objects.create(
            inn='987654321',
            company_name='Other Partner',
            status=BusinessPartner.Status.DRAFT,
        )

    def setUp(self):
        self.client.force_authenticate(self.product_owner_user)

    def test_business_partner_list_returns_restaurants_summary_sorted_by_name(self):
        Restaurant.objects.create(name='Zeta Restaurant', business_partner=self.partner)
        Restaurant.objects.create(name='Alpha Restaurant', business_partner=self.partner)
        Restaurant.objects.create(name='Beta Restaurant', business_partner=self.partner)
        Restaurant.objects.create(name='Other Restaurant', business_partner=self.other_partner)

        response = self.client.get('/api/v1/admin/platform/business-partners/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = next(item for item in response.data['data'] if item['id'] == str(self.partner.id))

        self.assertEqual(row['restaurants_count'], 3)
        self.assertEqual(
            [restaurant['name'] for restaurant in row['restaurants']],
            ['Alpha Restaurant', 'Beta Restaurant', 'Zeta Restaurant'],
        )

    def test_activation_defaults_returns_generated_credentials(self):
        response = self.client.get(f'/api/v1/admin/platform/business-partners/{self.partner.id}/activation-defaults/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['username'], 'bh-123456789')
        self.assertTrue(response.data['password'])

    def test_activate_accepts_manual_credentials(self):
        response = self.client.post(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/activate/',
            {
                'username': '  manual-login  ',
                'password': 'manual-pass-123',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.partner.refresh_from_db()
        owner_user = self.partner.owner_user

        self.assertIsNotNone(owner_user)
        self.assertEqual(response.data['username'], 'manual-login')
        self.assertEqual(owner_user.username, 'manual-login')
        self.assertTrue(owner_user.check_password('manual-pass-123'))
        self.assertEqual(owner_user.role, self.business_partner_role)
        self.assertEqual(self.partner.status, BusinessPartner.Status.ACTIVE)

    def test_activate_without_payload_keeps_legacy_generated_credentials_flow(self):
        response = self.client.post(f'/api/v1/admin/platform/business-partners/{self.partner.id}/activate/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.partner.refresh_from_db()
        owner_user = self.partner.owner_user

        self.assertIsNotNone(owner_user)
        self.assertEqual(response.data['username'], 'bh-123456789')
        self.assertTrue(response.data['password'])
        self.assertTrue(owner_user.check_password(response.data['password']))
        self.assertEqual(self.partner.status, BusinessPartner.Status.ACTIVE)
