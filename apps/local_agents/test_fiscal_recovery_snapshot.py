from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import CashShift, Payment, Receipt
from apps.local_agents.sync import _order_snapshot
from apps.restaurants.models import Restaurant, CashDesk
from apps.sales.models import Order
from apps.users.models import User


class FiscalRecoverySnapshotTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.restaurant = Restaurant.objects.create(name='Recovery')
        self.user = User.objects.create(username='recovery', full_name='Recovery')
        self.desk = CashDesk.objects.create(restaurant=self.restaurant, name='Kassa')
        self.shift = CashShift.objects.create(cash_desk=self.desk, opened_by=self.user,
                                             opened_at=self.now-timedelta(days=5))

    def old_order(self, restaurant=None):
        return Order.objects.create(restaurant=restaurant or self.restaurant,
                                    status=Order.Status.CLOSED,
                                    closed_at=self.now-timedelta(days=3))

    def snapshot_ids(self):
        return {str(row['id']) for row in _order_snapshot(self.restaurant, self.now)}

    def test_open_shift_keeps_original_payment_without_duplicates_or_date_changes(self):
        order = self.old_order()
        original_closed = order.closed_at
        for _ in range(2):
            Payment.objects.create(order=order, cash_shift=self.shift, amount=1000,
                                   method='cash', status='succeeded', register_fiscal=False)
        rows = _order_snapshot(self.restaurant, self.now)
        self.assertEqual([str(row['id']) for row in rows], [str(order.pk)])
        self.assertEqual(len(rows[0]['payments']), 2)
        order.refresh_from_db()
        self.assertEqual(order.closed_at, original_closed)
        self.shift.status = CashShift.Status.CLOSED
        self.shift.save()
        self.assertNotIn(str(order.pk), self.snapshot_ids())

    def test_unresolved_receipt_survives_history_window_until_sent(self):
        order = self.old_order()
        receipt = Receipt.objects.create(order=order, kind='fiscal', status='unknown')
        self.assertIn(str(order.pk), self.snapshot_ids())
        receipt.status = 'sent'
        receipt.save()
        self.assertNotIn(str(order.pk), self.snapshot_ids())

    def test_other_restaurant_evidence_is_excluded(self):
        other = Restaurant.objects.create(name='Other')
        order = self.old_order(other)
        Receipt.objects.create(order=order, kind='fiscal', status='unknown')
        self.assertNotIn(str(order.pk), self.snapshot_ids())
