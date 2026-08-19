import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.local_agents.models import LocalAgentMutationReceipt
from apps.restaurants.models import Restaurant


class MutationReceiptStorageCharacterizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Receipt storage one')
        cls.other_restaurant = Restaurant.objects.create(name='Receipt storage two')
        cls.user_id = uuid.uuid4()

    def create_receipt(self, **overrides):
        values = {
            'restaurant': self.restaurant,
            'operation_id': 'edge:storage-characterization',
            'user_id': self.user_id,
            'method': 'POST',
            'path': '/api/v1/pos/sales/orders/',
            'request_hash': 'a' * 64,
            'response_status': 201,
            'response_body': {'id': 'order-1', 'nested': {'value': 1}},
        }
        values.update(overrides)
        return LocalAgentMutationReceipt.objects.create(**values)

    def test_exact_fields_json_lookup_update_and_delete(self):
        receipt = self.create_receipt()

        stored = LocalAgentMutationReceipt.objects.get(operation_id=receipt.operation_id)
        self.assertEqual(stored.restaurant_id, self.restaurant.id)
        self.assertEqual(stored.user_id, self.user_id)
        self.assertEqual(stored.method, 'POST')
        self.assertEqual(stored.path, '/api/v1/pos/sales/orders/')
        self.assertEqual(stored.request_hash, 'a' * 64)
        self.assertEqual(stored.response_status, 201)
        self.assertEqual(stored.response_body, {'id': 'order-1', 'nested': {'value': 1}})

        stored.response_status = 204
        stored.response_body = {'reconciled': True, 'reason': 'already_absent'}
        stored.save(update_fields=['response_status', 'response_body', 'updated_at'])
        stored.refresh_from_db()
        self.assertEqual(stored.response_status, 204)
        self.assertEqual(stored.response_body, {'reconciled': True, 'reason': 'already_absent'})
        self.assertEqual(stored.request_hash, 'a' * 64)

        stored.delete()
        self.assertFalse(LocalAgentMutationReceipt.objects.filter(operation_id=receipt.operation_id).exists())

    def test_operation_id_is_globally_unique_across_restaurants(self):
        self.create_receipt(operation_id='edge:global-collision')

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_receipt(
                restaurant=self.other_restaurant,
                operation_id='edge:global-collision',
                request_hash='b' * 64,
            )

        self.assertEqual(
            LocalAgentMutationReceipt.objects.filter(operation_id='edge:global-collision').count(),
            1,
        )
