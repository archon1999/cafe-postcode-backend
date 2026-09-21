from rest_framework.test import APITestCase

from apps.restaurants.models import Restaurant, ServiceFeePolicy
from apps.users.models import User


class ServiceFeeFormulaApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Formula preview restaurant')
        cls.user = User.objects.create_superuser(username='formula-admin', password='test-only', full_name='Formula admin')

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.pk))

    def preview(self, source, parameters=None):
        return self.client.post('/api/v1/admin/restaurants/service-fees/preview/', {
            'definition': {'source': source, 'parameters': parameters or {}},
            'context': {'subtotal': 500000, 'started_at': '2026-09-21T17:30:00+05:00',
                        'calculated_at': '2026-09-21T18:30:00+05:00'},
        }, format='json')

    def test_catalog_contains_editable_technical_templates(self):
        response = self.client.get('/api/v1/admin/restaurants/service-fees/catalog/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(any(item['id'] == 'scheduled' for item in response.data['templates']))
        self.assertTrue(any(item['name'] == 'minutes_in' for item in response.data['functions']))
        self.assertFalse(any(item['id'] == 'percentage' for item in response.data['templates']))

    def test_simple_modes_keep_percentage_native_and_allow_direct_formula(self):
        url = '/api/v1/admin/restaurants/service-fees/assignments/'
        target = {'scope': 'restaurant', 'target_id': str(self.restaurant.pk)}
        response = self.client.post(url, {**target, 'mode': 'formula', 'formula': {
            'source': 'max(60, duration_minutes) * rate', 'parameters': {'rate': '1000'},
        }}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.service_fee_mode, 'formula')
        self.assertIn('program', self.restaurant.service_fee_formula)
        response = self.client.post(url, {**target, 'mode': 'percentage', 'percent': '12.50'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.restaurant.refresh_from_db()
        self.assertTrue(self.restaurant.service_fee_enabled)
        self.assertEqual(self.restaurant.service_fee_mode, 'percentage')
        self.assertEqual(float(self.restaurant.service_fee_percent), 12.5)
        self.assertEqual(self.restaurant.service_fee_formula, {})
        response = self.client.post(url, {**target, 'mode': 'none'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.service_fee_enabled)

    def test_simple_modes_reject_missing_rate_or_invalid_formula(self):
        url = '/api/v1/admin/restaurants/service-fees/assignments/'
        target = {'scope': 'restaurant', 'target_id': str(self.restaurant.pk)}
        for body in ({'mode': 'percentage'}, {'mode': 'percentage', 'percent': 0},
                     {'mode': 'formula', 'formula': {'source': 'unknown'}}, {'mode': 'hourly'}):
            response = self.client.post(url, {**target, **body}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.service_fee_enabled)

    def test_preview_preserves_case_sensitive_parameter_identifiers(self):
        response = self.preview('dayRate + day_rate', {'dayRate': '60000', 'day_rate': '120000'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['result']['amount'], 180000)
        self.assertEqual(response.json()['definition']['parameters'], {'dayRate': '60000', 'day_rate': '120000'})
        self.restaurant.refresh_from_db()
        self.assertFalse(self.restaurant.service_fee_enabled)

    def test_invalid_source_returns_position(self):
        response = self.preview('subtotal + unknown')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['valid'])
        self.assertEqual(response.data['errors'][0]['position'], 11)

    def test_runtime_error_is_explicit(self):
        response = self.preview('subtotal / 0')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['message'], 'Division by zero.')

    def test_pure_authoring_works_before_a_restaurant_is_selected(self):
        self.client.credentials()
        self.assertEqual(self.preview('100').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/admin/restaurants/service-fees/catalog/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/admin/restaurants/service-fees/assignments/').status_code, 400)
        self.assertFalse(ServiceFeePolicy.objects.exists())

    def test_anonymous_is_denied(self):
        self.client.force_authenticate(None)
        self.assertIn(self.preview('100').status_code, (401, 403))

    def test_user_without_admin_permission_is_denied(self):
        outsider = User.objects.create_user(username='formula-outsider', password='test-only', full_name='Outsider')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.preview('100').status_code, 403)

    def create_policy(self):
        response = self.client.post('/api/v1/admin/restaurants/service-fees/policies/', {
            'name': 'VIP soatlik', 'definition': {
                'source': 'max(60, duration_minutes) / 60 * hourly_rate',
                'parameters': {'hourly_rate': '60000'},
            },
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_policy_is_scoped_and_can_be_reused(self):
        policy = self.create_policy()
        self.assertEqual(ServiceFeePolicy.objects.get(pk=policy['id']).restaurant_id, self.restaurant.pk)
        response = self.client.get('/api/v1/admin/restaurants/service-fees/policies/')
        self.assertEqual(len(response.data), 1)
        another = Restaurant.objects.create(name='Another restaurant')
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(another.pk))
        self.assertEqual(self.client.get('/api/v1/admin/restaurants/service-fees/policies/').data, [])
        response = self.client.patch(f"/api/v1/admin/restaurants/service-fees/policies/{policy['id']}/", {
            'name': 'Cross tenant update', 'expected_revision': policy['revision'],
        }, format='json')
        self.assertEqual(response.status_code, 404)

    def test_policy_edits_require_current_revision_and_preserve_old_definition(self):
        original = self.create_policy()
        old_definition = dict(original['definition'])
        url = f"/api/v1/admin/restaurants/service-fees/policies/{original['id']}/"
        response = self.client.patch(url, {'definition': {'source': 'subtotal * 0.1'},
                                          'expected_revision': original['revision']}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data['revision'], original['revision'])
        self.assertEqual(old_definition['parameters']['hourly_rate'], '60000')
        stale = self.client.patch(url, {'name': 'Stale edit', 'expected_revision': original['revision']}, format='json')
        self.assertEqual(stale.status_code, 400)
        self.assertIn('expected_revision', stale.data)

    def test_invalid_policy_is_not_persisted(self):
        response = self.client.post('/api/v1/admin/restaurants/service-fees/policies/', {
            'name': 'Broken', 'definition': {'source': 'unknown * 100'},
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ServiceFeePolicy.objects.exists())

    def test_disabling_policy_changes_revision(self):
        original = self.create_policy()
        response = self.client.patch(f"/api/v1/admin/restaurants/service-fees/policies/{original['id']}/", {
            'is_active': False, 'expected_revision': original['revision'],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_active'])
        self.assertNotEqual(original['revision'], response.data['revision'])

    def test_assignment_pins_policy_revision_to_restaurant(self):
        policy = self.create_policy()
        response = self.client.post('/api/v1/admin/restaurants/service-fees/assignments/', {
            'scope': 'restaurant', 'target_id': str(self.restaurant.pk), 'policy_id': policy['id'],
            'expected_revision': policy['revision'],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.service_fee_mode, 'formula')
        original_definition = self.restaurant.service_fee_formula
        row = ServiceFeePolicy.objects.get(pk=policy['id'])
        row.definition['parameters']['hourly_rate'] = '120000'
        row.save()
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.service_fee_formula, original_definition)
        assignments = self.client.get('/api/v1/admin/restaurants/service-fees/assignments/')
        self.assertEqual(assignments.status_code, 200)
        self.assertEqual(assignments.data[0]['formula']['parameters']['hourly_rate'], '60000')

    def test_assignment_cannot_target_another_restaurant(self):
        policy = self.create_policy()
        other = Restaurant.objects.create(name='Other')
        response = self.client.post('/api/v1/admin/restaurants/service-fees/assignments/', {
            'scope': 'restaurant', 'target_id': str(other.pk), 'policy_id': policy['id'],
            'expected_revision': policy['revision'],
        }, format='json')
        self.assertEqual(response.status_code, 404)
