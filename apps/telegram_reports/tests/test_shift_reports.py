from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from apps.billing.models import Payment
from apps.billing.serializers.cash_shift import CashShiftSerializer
from apps.billing.services import CashShiftService
from apps.billing.services.shift_items import build_shift_sold_items
from apps.local_agents.sync import _cash_shift_snapshot, _print_templates
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase
from apps.telegram_reports.client import TelegramAPIError
from apps.telegram_reports.models import TelegramAccount, TelegramBranchSubscription, TelegramShiftDelivery
from apps.telegram_reports.services.shift_report import render_shift_report
from apps.telegram_reports.tasks import send_shift_reports


class ShiftReportsTests(PosTestCase):
    def setUp(self):
        self.shift = self.create_cash_shift()
        self.shift.opened_at = timezone.now() - timedelta(days=1)
        self.shift.save()
        self.order = Order.objects.create(restaurant=self.restaurant, status='closed', closed_at=timezone.now())
        OrderItem.objects.create(order=self.order, catalog_item=self.catalog_item, quantity=Decimal('1.250'), sale_unit='kg', unit_price=30000)
        OrderItem.objects.create(order=self.order, catalog_item=self.catalog_item, quantity=99, status='cancelled', unit_price=30000)
        for amount in (10000, 27500):
            Payment.objects.create(order=self.order, cash_shift=self.shift, cash_desk=self.cash_desk,
                                   amount=amount, status='succeeded', register_fiscal=False, paid_at=timezone.now())
        self.account = TelegramAccount.objects.create(telegram_user_id=123, chat_id=123)
        TelegramBranchSubscription.objects.create(account=self.account, restaurant=self.restaurant)

    def close(self, include=False):
        with patch.object(CashShiftService, 'ensure_shift_can_close'):
            return CashShiftService().close_shift(shift=self.shift, actual_closing_cash_amount=None,
                closed_by=self.user, include_sold_items=include)

    def test_split_payment_quantities_and_bootstrap_match(self):
        rows = build_shift_sold_items(self.shift)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['quantity'], rows[0]['revenue']), (1.25, 37500))
        snapshot = _cash_shift_snapshot(self.restaurant)[0]
        self.assertEqual(snapshot['soldItems'][0]['saleUnit'], 'kg')
        self.assertEqual(snapshot['soldOrderIds'], [str(self.order.pk)])
        self.assertEqual(CashShiftSerializer(self.shift).data['sold_items'], rows)
        self.assertTrue(any(row['kind'] == 'shift_report' for row in _print_templates(self.restaurant)))

    def test_other_shift_and_unpaid_orders_are_excluded(self):
        other = self.create_cash_shift()
        Payment.objects.create(order=self.order, cash_shift=other, amount=1, status='succeeded', paid_at=timezone.now())
        self.assertEqual(build_shift_sold_items(self.shift), [])
        self.assertEqual(len(build_shift_sold_items(other)), 1)

    def test_discount_is_allocated_proportionally_without_changing_quantities(self):
        self.order.items.all().delete()
        OrderItem.objects.create(order=self.order, catalog_item=self.catalog_item, quantity=2, sale_unit='piece', unit_price=30000)
        OrderItem.objects.create(order=self.order, catalog_item=self.catalog_item, quantity=Decimal('1.250'), sale_unit='kg', unit_price=32000)
        OrderItem.objects.create(order=self.order, catalog_item=self.catalog_item, quantity=99, unit_price=90000, status='cancelled')
        for calculated, final, expected in [(100000, 90000, [54000, 36000]), (100000, 99999, [59999, 40000]), (110000, 99000, [54000, 36000])]:
            with self.subTest(calculated=calculated, final=final):
                self.order.subtotal = 100000
                self.order.calculated_total = calculated
                self.order.total = self.order.total_override = final
                self.order.save()
                rows = build_shift_sold_items(self.shift)
                self.assertEqual([row['revenue'] for row in rows], expected)
                self.assertEqual([row['quantity'] for row in rows], [2, 1.25])
                self.assertEqual([row['revenue'] for row in _cash_shift_snapshot(self.restaurant)[0]['soldItems']], expected)
        closed = self.close(True)
        document = CashShiftService().create_shift_report_documents(shift=closed, closed=True)[0]
        self.assertEqual([row['lineTotal'] for row in document.data_snapshot['items']], [54000, 36000])
        self.assertIn('54 ming', render_shift_report(closed))

    def test_close_print_defaults_off_and_opt_in_contains_items(self):
        shift = self.close()
        document = CashShiftService().create_shift_report_documents(shift=shift, closed=True)[0]
        self.assertEqual(document.data_snapshot['items'], [])
        # Inspect the same immutable sold rows using an explicitly opted-in report.
        from apps.printing.services.shift_report_snapshot import build_shift_report_print_snapshot
        report = dict(shift.close_report_payload['report']['pos_report'], SoldItems=shift.close_report_payload['sold_items'])
        snapshot = build_shift_report_print_snapshot(shift=shift, report=report, fiscal=False, closed=True)
        self.assertEqual(snapshot['items'][0]['quantity'], 1.25)
        self.assertEqual(snapshot['items'][0]['lineTotal'], 37500)

    def test_telegram_is_scoped_escaped_immutable_and_sent_once(self):
        self.restaurant.name = '<Branch & Cafe>'
        self.restaurant.save()
        shift = self.close(True)
        text = render_shift_report(shift)
        self.assertIn('&lt;Branch &amp; Cafe&gt;', text)
        self.assertIn(timezone.localtime(shift.opened_at).strftime('%d.%m.%Y %H:%M:%S'), text)
        self.assertIn('Osh', text)
        self.assertNotIn('💰', text)
        OrderItem.objects.filter(order=self.order).update(quantity=10)
        self.assertEqual(CashShiftSerializer(shift).data['sold_items'][0]['quantity'], 1.25)
        with patch('apps.telegram_reports.tasks.TelegramBotClient') as client:
            send_shift_reports(str(shift.pk))
            send_shift_reports(str(shift.pk))
            self.assertEqual(client.return_value.send_message.call_count, 1)
        self.assertIsNotNone(TelegramShiftDelivery.objects.get(shift=shift).sent_at)

    def test_opted_in_close_creates_product_print_document(self):
        shift = self.close(True)
        document = CashShiftService().create_shift_report_documents(shift=shift, closed=True)[0]
        self.assertEqual(document.data_snapshot['items'], [{
            'name': 'Osh', 'quantity': 1.25, 'saleUnit': 'kg', 'lineTotal': 37500,
        }])

    def test_close_queues_after_commit_and_same_day_shifts_have_distinct_deliveries(self):
        with patch('apps.telegram_reports.tasks.enqueue_shift_report') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                first = self.close()
                enqueue.assert_not_called()
            enqueue.assert_called_once_with(str(first.pk))
        self.shift = self.create_cash_shift()
        second = self.close()
        self.assertEqual(TelegramShiftDelivery.objects.filter(account=self.account).count(), 2)
        with patch('apps.telegram_reports.tasks.TelegramBotClient') as client:
            send_shift_reports(str(first.pk))
            send_shift_reports(str(second.pk))
            self.assertEqual(client.return_value.send_message.call_count, 2)

    def test_failed_chunk_resumes_without_resending_previous_chunks(self):
        shift = self.close()
        with patch('apps.telegram_reports.tasks.split_telegram_message', return_value=['first', 'second']), patch('apps.telegram_reports.tasks.TelegramBotClient') as client:
            client.return_value.send_message.side_effect = [{}, TelegramAPIError('temporary')]
            send_shift_reports(str(shift.pk))
            self.assertEqual(TelegramShiftDelivery.objects.get(shift=shift).next_chunk, 1)
            client.return_value.send_message.reset_mock(side_effect=True)
            send_shift_reports(str(shift.pk))
            client.return_value.send_message.assert_called_once_with(chat_id=123, text='second')
