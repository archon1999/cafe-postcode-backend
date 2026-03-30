from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import EmployeeProfile, User
from common.tests.pos_api import PosTestDataMixin


class PosPinLoginApiTests(PosTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.set_pin('1111')
        cls.user.save(update_fields=['pin_code'])

        cls.inactive_user = User.objects.create_user(
            username='inactive-pos-user',
            password='secret123',
            full_name='Inactive POS User',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.role,
            ui_mode=User.UiMode.POS,
            is_active=False,
        )
        cls.inactive_user.set_pin('2222')
        cls.inactive_user.save(update_fields=['pin_code'])
        cls.inactive_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.INACTIVE
        cls.inactive_user.employee_profile.save(update_fields=['employment_status'])

        cls.archived_user = User.objects.create_user(
            username='archived-pos-user',
            password='secret123',
            full_name='Archived POS User',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.role,
            ui_mode=User.UiMode.POS,
            is_active=False,
        )
        cls.archived_user.set_pin('3333')
        cls.archived_user.save(update_fields=['pin_code'])
        cls.archived_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.ARCHIVED
        cls.archived_user.employee_profile.save(update_fields=['employment_status'])

    def test_pos_pin_login_accepts_four_digit_pin_for_active_employee(self):
        response = self.client.post('/api/v1/pos/auth/pin-login/', {'pin': '1111'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], self.user.username)
        self.assertIn('feature_config', response.data)

    def test_pos_pin_login_rejects_inactive_employee_with_explicit_message(self):
        response = self.client.post('/api/v1/pos/auth/pin-login/', {'pin': '2222'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('inactive', response.data['pin'][0].lower())

    def test_pos_pin_login_rejects_archived_employee_with_explicit_message(self):
        response = self.client.post('/api/v1/pos/auth/pin-login/', {'pin': '3333'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('archived', response.data['pin'][0].lower())

    def test_pos_pin_login_requires_exactly_four_digits(self):
        response = self.client.post('/api/v1/pos/auth/pin-login/', {'pin': '11111'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('4', str(response.data['pin'][0]))
