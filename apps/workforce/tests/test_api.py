from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from PIL import Image

from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import AuthSession, Permission, Role, User
from apps.workforce.models import AttendancePunch, GeofenceConfig, Shift


@override_settings(ROOT_URLCONF='apps.workforce.tests.urls')
class WorkforceApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(name='First pilot branch')
        cls.second = Restaurant.objects.create(name='Second branch')
        cls.permissions = [
            Permission.objects.get_or_create(code=code, defaults={'name': code})[0]
            for code in ('workforce.view', 'workforce.schedule', 'workforce.approve', 'workforce.config')
        ]
        cls.first_entitlement = RestaurantEntitlement.objects.create(restaurant=cls.first, is_active=True)
        cls.first_entitlement.permissions.set(cls.permissions)
        cls.second_entitlement = RestaurantEntitlement.objects.create(restaurant=cls.second, is_active=True)
        cls.second_entitlement.permissions.set(cls.permissions)
        cls.role = Role.objects.create(code='workforce-test-manager', name='Workforce test manager')
        cls.role.permissions.set(cls.permissions)
        cls.employee = User.objects.create_user(
            username='workforce-api-employee', password='temporary-password',
            full_name='First Employee', restaurant=cls.first,
        )
        cls.manager = User.objects.create_user(
            username='workforce-api-manager', password='temporary-password',
            full_name='First Manager', restaurant=cls.first, role=cls.role,
        )
        cls.other = User.objects.create_user(
            username='workforce-api-other', password='temporary-password',
            full_name='Second Employee', restaurant=cls.second,
        )
        GeofenceConfig.objects.create(
            restaurant=cls.first, workforce_enabled=True, enabled=True,
            latitude=Decimal('41.311081'), longitude=Decimal('69.240562'), radius_meters=150,
        )
        GeofenceConfig.objects.create(restaurant=cls.second, workforce_enabled=True)
        cls.manager_session = AuthSession.objects.create(
            user=cls.manager, restaurant=cls.first, surface='staff',
            token_key_hash='a' * 64, expires_at=timezone.now() + timedelta(hours=1),
        )
        cls.employee_session = AuthSession.objects.create(
            user=cls.employee, restaurant=cls.first, surface='staff',
            token_key_hash='b' * 64, expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_staff_punch_accepts_outside_geofence_and_is_idempotent(self):
        self.client.force_authenticate(self.employee, token=self.employee_session)
        payload = {
            'type': 'in', 'clientEventId': 'pwa-outside-12345',
            'latitude': '41.320000', 'longitude': '69.240562', 'accuracyMeters': 20,
        }
        first = self.client.post('/api/v1/staff/workforce/attendance/punch/', payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertTrue(first.data['punch']['requires_review'])
        second = self.client.post('/api/v1/staff/workforce/attendance/punch/', payload, format='json')
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(AttendancePunch.objects.count(), 1)

    def test_optional_selfie_is_private_and_uses_verified_mime_type(self):
        self.client.force_authenticate(self.employee, token=self.employee_session)
        buffer = BytesIO()
        Image.new('RGB', (2, 2), 'brown').save(buffer, format='JPEG')
        selfie = SimpleUploadedFile('selfie.jpg', buffer.getvalue(), content_type='text/html')
        created = self.client.post('/api/v1/staff/workforce/attendance/punch/', {
            'type': 'in', 'clientEventId': 'pwa-selfie-0001',
            'latitude': '41.311081', 'longitude': '69.240562', 'accuracyMeters': '20',
            'selfie': selfie,
        }, format='multipart')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        punch_id = created.data['punch']['id']
        response = self.client.get(f'/api/v1/staff/workforce/attendance/{punch_id}/selfie/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_manager_scope_and_other_branch_employee_rejected(self):
        Shift.objects.create(
            restaurant=self.second, employee=self.other,
            starts_at=timezone.now() + timedelta(hours=1), ends_at=timezone.now() + timedelta(hours=9),
            status=Shift.Status.PUBLISHED,
        )
        self.client.force_authenticate(self.manager, token=self.manager_session)
        team = self.client.get('/api/v1/staff/manager/workforce/team/')
        self.assertEqual(team.status_code, status.HTTP_200_OK, team.data)
        ids = {row['employee']['id'] for row in team.data}
        self.assertNotIn(str(self.other.id), {str(item) for item in ids})
        start = timezone.now() + timedelta(days=1)
        response = self.client.post('/api/v1/staff/manager/workforce/shifts/', {
            'employeeId': str(self.other.id),
            'startsAt': start.isoformat(), 'endsAt': (start + timedelta(hours=8)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_staff_endpoint_rejects_admin_surface_even_for_same_user(self):
        admin_session = AuthSession.objects.create(
            user=self.employee, restaurant=self.first, surface='admin',
            token_key_hash='c' * 64, expires_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_authenticate(self.employee, token=admin_session)
        response = self.client.get('/api/v1/staff/workforce/today/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_disabled_branch_denies_staff_but_manager_can_enable_pilot(self):
        config = GeofenceConfig.objects.get(restaurant=self.first)
        config.workforce_enabled = False
        config.save(update_fields=['workforce_enabled'])
        self.client.force_authenticate(self.employee, token=self.employee_session)
        self.assertEqual(self.client.get('/api/v1/staff/workforce/today/').status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.manager, token=self.manager_session)
        response = self.client.put('/api/v1/staff/manager/workforce/geofence/', {
            'workforceEnabled': True, 'enabled': True,
            'latitude': '41.311081', 'longitude': '69.240562', 'radiusMeters': 150,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        config.refresh_from_db()
        self.assertTrue(config.workforce_enabled)

    def test_device_import_is_branch_scoped_and_idempotent(self):
        agent = SimpleNamespace(restaurant=self.first, device_id=uuid4())
        path = '/api/v1/local-agent/workforce/attendance/import/'
        event = {
            'terminalId': 'front-door', 'sourceEventId': 'hik-1001',
            'employeeId': str(self.other.id), 'type': 'in',
            'deviceRecordedAt': timezone.now().isoformat(),
        }
        with patch('apps.workforce.api.importer.views.authenticate_local_agent', return_value=agent):
            denied = self.client.post(path, {'events': [event]}, format='json', HTTP_X_DEVICE_ID=str(agent.device_id))
            self.assertEqual(denied.status_code, status.HTTP_400_BAD_REQUEST, denied.data)
            event['employeeId'] = str(self.employee.id)
            first = self.client.post(path, {'events': [event]}, format='json', HTTP_X_DEVICE_ID=str(agent.device_id))
            self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
            again = self.client.post(path, {'events': [event]}, format='json', HTTP_X_DEVICE_ID=str(agent.device_id))
            self.assertEqual(again.status_code, status.HTTP_200_OK, again.data)
            self.assertTrue(again.data['results'][0]['duplicate'])
            self.assertEqual(AttendancePunch.objects.count(), 1)
