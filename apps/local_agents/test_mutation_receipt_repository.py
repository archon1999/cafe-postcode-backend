import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.local_agents.models import LocalAgentMutationReceipt
from apps.local_agents.repositories import MutationReceiptRepository
from apps.restaurants.models import Restaurant


class MutationReceiptRepositoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Repository one')
        cls.other_restaurant = Restaurant.objects.create(name='Repository two')
        cls.user_id = uuid.uuid4()

    def setUp(self):
        self.repository = MutationReceiptRepository()

    def receipt_values(self, **overrides):
        values = {
            'restaurant': self.restaurant,
            'operation_id': 'edge:repository',
            'user_id': self.user_id,
            'method': 'POST',
            'path': '/api/v1/pos/sales/orders/',
            'request_hash': 'a' * 64,
            'response_status': 201,
            'response_body': {'id': 'order-1'},
        }
        values.update(overrides)
        return values

    def test_direct_orm_write_is_read_updated_and_deleted_by_repository(self):
        direct = LocalAgentMutationReceipt.objects.create(**self.receipt_values())

        stored = self.repository.find(operation_id=direct.operation_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.id, direct.id)
        self.assertEqual(stored.response_body, {'id': 'order-1'})

        self.repository.update_response(
            receipt=stored,
            response_status=204,
            response_body={'reconciled': True, 'reason': 'already_absent'},
        )
        direct.refresh_from_db()
        self.assertEqual(direct.response_status, 204)
        self.assertEqual(direct.response_body, {'reconciled': True, 'reason': 'already_absent'})

        self.repository.delete(receipt=direct)
        self.assertIsNone(self.repository.find(operation_id=direct.operation_id))

    def test_repository_write_is_visible_to_direct_orm_and_keeps_global_uniqueness(self):
        created = self.repository.create(**self.receipt_values())

        direct = LocalAgentMutationReceipt.objects.get(operation_id=created.operation_id)
        self.assertEqual(direct.id, created.id)
        self.assertEqual(direct.restaurant_id, self.restaurant.id)
        self.assertEqual(direct.user_id, self.user_id)
        self.assertEqual(direct.method, 'POST')
        self.assertEqual(direct.path, '/api/v1/pos/sales/orders/')
        self.assertEqual(direct.request_hash, 'a' * 64)
        self.assertEqual(direct.response_status, 201)
        self.assertEqual(direct.response_body, {'id': 'order-1'})

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.repository.create(
                **self.receipt_values(
                    restaurant=self.other_restaurant,
                    operation_id=created.operation_id,
                    request_hash='b' * 64,
                )
            )

        self.assertEqual(
            LocalAgentMutationReceipt.objects.filter(operation_id=created.operation_id).count(),
            1,
        )

    def test_missing_operation_returns_none(self):
        self.assertIsNone(self.repository.find(operation_id='edge:missing'))
