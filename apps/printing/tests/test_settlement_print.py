from decimal import Decimal

from apps.billing.models import Payment, Receipt
from apps.integrations.models import IntegrationConfig
from apps.integrations.services.fiscal_drive import FiscalDriveIntegrationService
from apps.printing.services.print_snapshots import build_payment_print_snapshot
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase


class SettlementPrintTests(PosTestCase):
    def test_discount_and_mixed_tender_match_fiscal_lines(self):
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save()
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch,
            distribution_point=self.hall_distribution, opened_by=self.user,
            order_number=1, channel='hall', guest_count=1)
        item = OrderItem.objects.create(order=order, catalog_item=self.catalog_item,
            prep_station=self.prep_station, created_by=self.user, quantity=1, unit_price=18000)
        order.recalculate_totals()
        order.total_override = 17820
        order.save(update_fields=['total_override'])
        order.recalculate_totals(preserve_override=True)
        shift = self.create_cash_shift()
        for method, amount in [('cash', 6000), ('card', 6000), ('cash', 5820)]:
            payment = Payment.objects.create(order=order, cash_shift=shift, cash_desk=self.cash_desk,
                received_by=self.user, method=method, amount=amount, status='succeeded')
        receipt = Receipt.objects.create(order=order, payment=payment, kind='plain')
        snapshot = build_payment_print_snapshot(receipt=receipt)
        self.assertEqual(snapshot['payment']['cash'], 11820)
        self.assertEqual(snapshot['payment']['card'], 6000)
        self.assertEqual(snapshot['payment']['amount'], 17820)
        self.assertEqual(snapshot['payment']['method'], 'Aralash')
        self.assertEqual(snapshot['items'][0]['lineTotal'], 16200)
        self.assertEqual(snapshot['items'][0]['unitPrice'], 16200)
        self.assertEqual(snapshot['totals']['serviceFee'], 1620)
        self.assertEqual(snapshot['totals']['restaurantServiceFee'], 1620)
        self.assertEqual(snapshot['totals']['vat'], 1909.28)
        totals = snapshot['totals']
        self.assertEqual(totals['subtotal'] + totals['serviceFee'] + totals.get('totalAdjustment', 0), totals['total'])
        config = IntegrationConfig.objects.create(restaurant=self.restaurant, name='Print QA', kind='fiscal', provider='fiscal-drive-service')
        fiscal_items = FiscalDriveIntegrationService(config)._build_sale_items(order=order)
        self.assertEqual(sum(row['Price'] for row in fiscal_items), 1782000)
        self.assertEqual(sum(row.get('VAT', 0) for row in fiscal_items), int(Decimal(str(snapshot['totals']['vat'])) * 100))
        item.refresh_from_db()
        self.assertEqual(item.line_total, 18000)
