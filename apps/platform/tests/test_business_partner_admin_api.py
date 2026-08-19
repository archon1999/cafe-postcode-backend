from rest_framework import status
from rest_framework.test import APITestCase

from apps.platform.models import BusinessPartner
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


class BusinessPartnerAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product_owner_role = Role.objects.get(code='product_owner')
        cls.business_partner_role = Role.objects.get(code='business_partner')
        cls.custom_tariff_permission = Permission.objects.get(code='restaurants.custom_tariff')

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
        self.assertFalse(row['custom_tariff_allowed'])

    def test_business_partner_serializer_persists_custom_tariff_permission(self):
        response = self.client.patch(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/',
            {'custom_tariff_allowed': True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['custom_tariff_allowed'])
        self.assertTrue(self.partner.extra_permissions.filter(code='restaurants.custom_tariff').exists())

        response = self.client.patch(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/',
            {'custom_tariff_allowed': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['custom_tariff_allowed'])
        self.assertFalse(self.partner.extra_permissions.filter(code='restaurants.custom_tariff').exists())

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
                'password': 'Partner-Control!9x7Q',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.partner.refresh_from_db()
        owner_user = self.partner.owner_user

        self.assertIsNotNone(owner_user)
        self.assertEqual(response.data['username'], 'manual-login')
        self.assertEqual(owner_user.username, 'manual-login')
        self.assertTrue(owner_user.check_password('Partner-Control!9x7Q'))
        self.assertEqual(owner_user.role, self.business_partner_role)
        self.assertFalse(owner_user.is_staff)
        self.assertFalse(owner_user.is_superuser)
        self.assertEqual(self.partner.status, BusinessPartner.Status.ACTIVE)

    def test_reactivation_clears_non_superuser_staff_but_preserves_real_superuser(self):
        owner = User.objects.create_user(
            username='legacy-partner-staff',
            password='secret123',
            full_name='Legacy Partner Staff',
            role=self.business_partner_role,
            is_staff=True,
            is_superuser=False,
        )
        self.partner.owner_user = owner
        self.partner.save(update_fields=['owner_user'])

        response = self.client.post(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/activate/',
            {'username': 'legacy-partner-staff', 'password': 'Partner-Reactivate!7mQ'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        owner.refresh_from_db()
        self.assertFalse(owner.is_staff)

        owner.is_staff = True
        owner.is_superuser = True
        owner.save(update_fields=['is_staff', 'is_superuser'])
        response = self.client.post(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/activate/',
            {'username': 'legacy-partner-staff', 'password': 'Partner-Superuser!8zR'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        owner.refresh_from_db()
        self.assertTrue(owner.is_staff)
        self.assertTrue(owner.is_superuser)

    def test_activation_rejects_a_weak_manual_password(self):
        response = self.client.post(
            f'/api/v1/admin/platform/business-partners/{self.partner.id}/activate/',
            {'username': 'weak-partner-login', 'password': '12345678'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('password', response.data)
        self.partner.refresh_from_db()
        self.assertIsNone(self.partner.owner_user)
        self.assertEqual(self.partner.status, BusinessPartner.Status.DRAFT)

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
