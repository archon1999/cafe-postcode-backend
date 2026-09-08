from copy import deepcopy
from unittest.mock import patch

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.billing.api.pos.views.payments import PaymentFiscalRetryView
from apps.billing.models import Payment, Receipt
from apps.billing.services.fiscal_retry_validation_desk import fiscal_retry_validation_desk
from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import CashDesk, Restaurant
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosTestCase


class FiscalRetryValidationDeskTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.integration = IntegrationConfig.objects.create(
            restaurant=self.restaurant, kind='fiscal', provider='fiscal-drive-service', is_enabled=True,
        )
        self.desk = CashDesk.objects.create(restaurant=self.restaurant, name='Replacement', fiscal_integration=self.integration)
        order = Order.objects.create(
            restaurant=self.restaurant, branch=self.branch, distribution_point=self.takeaway_distribution,
            opened_by=self.user, cashier=self.user, order_number=987, channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED, total=30000,
        )
        self.payment = Payment.objects.create(
            order=order, received_by=self.user, method='cash', amount=30000, status='succeeded',
            cash_desk=None, register_fiscal=True, financial_snapshot={'orderTotal': 30000},
        )
        self.evidence = {
            'ok': True, 'provider': 'fiscal-drive-service', 'terminal_id': 'RECOVERY-TEST',
            'receipt_number': '16', 'txid': 16,
            'request': {'receipt': {'ReceivedCash': 3000000, 'ReceivedCard': 0}},
        }

    def resolve(self, payload=None, trusted=True):
        return fiscal_retry_validation_desk(payment=self.payment, payload=payload or {}, trusted_edge_replay=trusted)

    def invoke(self, payload, trusted=True):
        request = APIRequestFactory().post('/api/v1/pos/billing/payments/retry-fiscal/', payload, format='json')
        request.trusted_edge_replay = trusted
        force_authenticate(request, self.user)
        return PaymentFiscalRetryView.as_view(permission_classes=[])(request, pk=self.payment.pk)

    def test_replay_persists_original_proof_idempotently_without_rebinding_payment(self):
        original = Payment.objects.filter(pk=self.payment.pk).values().get()
        payload = {'edge_cash_desk_id': str(self.desk.pk), 'edge_fiscal_results': [self.evidence]}
        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as device:
            first = self.invoke(payload)
            self.assertEqual(first.status_code, 200, first.data)
            retained = Receipt.objects.get(payment=self.payment, kind='fiscal')
            retained_id, retained_payload = retained.pk, deepcopy(retained.payload)
            second = self.invoke(payload)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(first.data['fiscalComplete'])
        device.assert_not_called()
        receipts = Receipt.objects.filter(payment=self.payment, kind='fiscal')
        self.assertEqual(receipts.count(), 1)
        self.assertEqual(receipts.get().pk, retained_id)
        self.assertEqual(receipts.get().payload, retained_payload)
        self.assertEqual(retained_payload['txid'], 16)
        self.assertEqual(retained_payload['receipt_number'], '16')
        self.assertEqual(retained_payload['terminal_id'], 'RECOVERY-TEST')
        self.assertEqual(Payment.objects.filter(pk=self.payment.pk).values().get(), original)

    def test_explicit_camel_case_desk_is_accepted(self):
        self.assertEqual(self.resolve({'edgeCashDeskId': str(self.desk.pk)}), self.desk)

    def test_missing_malformed_and_unknown_ids_rejected(self):
        for value in (None, '', 'not-a-uuid', '00000000-0000-0000-0000-000000000001', {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.resolve({'edge_cash_desk_id': value})

    def test_untrusted_browser_cannot_use_fallback_or_submit_proof(self):
        with self.assertRaises(ValidationError):
            self.resolve({'edgeCashDeskId': str(self.desk.pk)}, trusted=False)
        with patch('apps.billing.api.pos.views.payments.dispatch_to_financial_owner', return_value=Response({'routed': True})) as dispatch:
            response = self.invoke({'edgeCashDeskId': str(self.desk.pk), 'edge_fiscal_results': [self.evidence]}, trusted=False)
        dispatch.assert_called_once()
        self.assertEqual(response.data, {'routed': True})
        self.assertFalse(Receipt.objects.filter(payment=self.payment).exists())

    def test_foreign_desk_and_foreign_integration_rejected(self):
        other = Restaurant.objects.create(name='Other')
        self.desk.restaurant = other
        self.desk.save(update_fields=['restaurant'])
        with self.assertRaises(ValidationError):
            self.resolve({'edgeCashDeskId': str(self.desk.pk)})
        self.desk.restaurant = self.restaurant
        self.desk.save(update_fields=['restaurant'])
        self.integration.restaurant = other
        self.integration.save(update_fields=['restaurant'])
        with self.assertRaises(ValidationError):
            self.resolve({'edgeCashDeskId': str(self.desk.pk)})

    def test_inactive_desk_disabled_wrong_kind_or_missing_integration_rejected(self):
        for field, value in [('is_active', False), ('fiscal_integration', None)]:
            original = getattr(self.desk, field)
            setattr(self.desk, field, value)
            self.desk.save(update_fields=[field])
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.resolve({'edgeCashDeskId': str(self.desk.pk)})
            setattr(self.desk, field, original)
            self.desk.save(update_fields=[field])
        for field, value in [('is_enabled', False), ('kind', 'printer')]:
            original = getattr(self.integration, field)
            setattr(self.integration, field, value)
            self.integration.save(update_fields=[field])
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.resolve({'edgeCashDeskId': str(self.desk.pk)})
            setattr(self.integration, field, original)
            self.integration.save(update_fields=[field])

    def test_existing_payment_desk_remains_authoritative(self):
        self.payment.cash_desk = self.cash_desk
        self.payment.save(update_fields=['cash_desk'])
        self.assertEqual(self.resolve({'edgeCashDeskId': str(self.desk.pk)}), self.cash_desk)

    def test_original_amount_and_provider_validation_still_reject_invalid_evidence(self):
        for kind in ('provider', 'amount'):
            evidence = deepcopy(self.evidence)
            if kind == 'provider':
                evidence['provider'] = 'other-provider'
            else:
                evidence['request']['receipt']['ReceivedCash'] = 4000000
            response = self.invoke({'edge_cash_desk_id': str(self.desk.pk), 'edge_fiscal_results': [evidence]})
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Receipt.objects.filter(payment=self.payment).exists())
