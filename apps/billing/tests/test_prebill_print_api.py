from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from apps.billing.models import CashShift, Receipt
from apps.integrations.models import IntegrationConfig
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User


class PrebillPrintApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.session = self.create_table_session()
        self.order_data = self.create_order_via_api(
            {
                'table_session': str(self.session.id),
                'distribution_point': str(self.hall_distribution.id),
                'channel': Order.Channel.HALL,
                'guest_count': 4,
                'note': 'Mehmonlar kutmoqda',
            }
        )
        self.order_id = self.order_data['id']
        self.add_item_via_api(self.order_id, quantity=2, note='Issiqroq')

    def configure_live_printer(self, *, printer_name='POS-80 USB'):
        printer, _ = IntegrationConfig.objects.update_or_create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            defaults={
                'is_enabled': True,
                'settings': {
                    'printer_name': printer_name,
                    'paper_width_mm': 80,
                    'cut_after_print': True,
                    'encoding': 'cp437',
                },
            },
        )
        return printer

    def create_other_shift_with_printer(self, *, printer_name='Shift POS-80'):
        printer = self.configure_live_printer(printer_name=printer_name)
        cash_desk = self.restaurant.cash_desks.create(
            name=f'{printer_name} cash desk',
            enabled_payment_methods=['cash', 'card', 'qr'],
            printer_integration=printer,
        )
        cashier = User.objects.create_user(
            username=f'{printer_name.lower().replace(" ", "-")}-cashier',
            password='secret123',
            full_name=f'{printer_name} Cashier',
            restaurant=self.restaurant,
            role=self.role,
        )
        CashShift.objects.create(
            cash_desk=cash_desk,
            cashier=cashier,
            opened_by=cashier,
            opened_at=timezone.now(),
        )
        return cash_desk

    def test_open_hall_order_prints_prebill_and_creates_receipt(self):
        printer = self.configure_live_printer()
        self.cash_desk.printer_integration = printer
        self.cash_desk.save(update_fields=['printer_integration', 'updated_at'])
        self.create_cash_shift(cash_desk=self.cash_desk)

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'printed_at': '2026-04-08T16:00:00+05:00',
            },
        ) as print_mock:
            response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['kind'], Receipt.Kind.PREBILL)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.SENT)
        self.assertEqual(response.data['result']['provider'], 'windows-raw')
        self.assertTrue(print_mock.called)
        receipt = Receipt.objects.get(pk=response.data['receipt']['id'])
        self.assertEqual(receipt.kind, Receipt.Kind.PREBILL)
        self.assertEqual(receipt.status, Receipt.Status.SENT)
        self.assertEqual(receipt.payload['snapshot']['order_note'], 'Mehmonlar kutmoqda')

    def test_active_shift_cash_desk_printer_takes_precedence_over_global_printer(self):
        cash_desk_printer = self.configure_live_printer(printer_name='Cash desk POS-80')
        self.cash_desk.printer_integration = cash_desk_printer
        self.cash_desk.save(update_fields=['printer_integration', 'updated_at'])
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='unsupported-printer',
            settings={'printer_name': 'Global fallback'},
        )
        self.create_cash_shift(cash_desk=self.cash_desk)

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'printer_name': 'Cash desk POS-80',
                'printed_at': '2026-04-08T16:00:00+05:00',
            },
        ) as print_mock:
            response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.SENT)
        self.assertEqual(response.data['result']['provider'], 'windows-raw')
        self.assertTrue(print_mock.called)

    def test_prebill_uses_any_open_shift_cash_desk_printer_when_user_has_no_active_shift(self):
        self.create_other_shift_with_printer(printer_name='Other shift POS-80')
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='unsupported-printer',
            settings={'printer_name': 'Global fallback'},
        )

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'printer_name': 'Other shift POS-80',
                'printed_at': '2026-04-08T16:00:00+05:00',
            },
        ) as print_mock:
            response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.SENT)
        self.assertEqual(response.data['result']['provider'], 'windows-raw')
        self.assertTrue(print_mock.called)

    def test_prebill_uses_other_open_shift_printer_when_active_shift_has_no_printer(self):
        self.create_cash_shift(cash_desk=self.cash_desk)
        self.create_other_shift_with_printer(printer_name='Available shift POS-80')
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='unsupported-printer',
            settings={'printer_name': 'Global fallback'},
        )

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'printer_name': 'Available shift POS-80',
                'printed_at': '2026-04-08T16:00:00+05:00',
            },
        ) as print_mock:
            response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.SENT)
        self.assertEqual(response.data['result']['provider'], 'windows-raw')
        self.assertTrue(print_mock.called)

    def test_prebill_does_not_use_global_printer_when_active_shift_has_no_printer(self):
        self.configure_live_printer()
        self.create_cash_shift(cash_desk=self.cash_desk)

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'printed_at': '2026-04-08T16:00:00+05:00',
            },
        ) as print_mock:
            response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['result']['code'], 'PRINTER_NOT_CONFIGURED')
        self.assertTrue(response.data['result']['requires_client_print'])
        self.assertFalse(print_mock.called)

    def test_missing_printer_config_returns_client_print_fallback(self):
        IntegrationConfig.objects.filter(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PRINTER).delete()

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['kind'], Receipt.Kind.PREBILL)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.CREATED)
        self.assertEqual(response.data['result']['code'], 'PRINTER_NOT_CONFIGURED')
        self.assertTrue(response.data['result']['requires_client_print'])

        receipt = Receipt.objects.get(pk=response.data['receipt']['id'])
        self.assertEqual(receipt.status, Receipt.Status.CREATED)
        self.assertEqual(receipt.payload['snapshot']['order_number'], self.order_data['order_number'])

    def test_client_print_result_callback_marks_receipt_sent(self):
        IntegrationConfig.objects.filter(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PRINTER).delete()
        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')
        receipt_id = response.data['receipt']['id']

        callback = self.client.post(
            f'/api/v1/pos/billing/receipts/{receipt_id}/print-result/',
            {'result': {'ok': True, 'provider': 'browser-print', 'detail': 'printed by browser'}},
            format='json',
        )

        self.assertEqual(callback.status_code, status.HTTP_200_OK, callback.data)
        self.assertEqual(callback.data['receipt']['status'], Receipt.Status.SENT)
        receipt = Receipt.objects.get(pk=receipt_id)
        self.assertEqual(receipt.status, Receipt.Status.SENT)
        self.assertEqual(receipt.payload['client_result']['detail'], 'printed by browser')

    def test_rejects_order_without_items(self):
        self.configure_live_printer()
        empty_session = self.create_table_session()
        empty_order = self.create_order_via_api(
            {
                'table_session': str(empty_session.id),
                'distribution_point': str(self.hall_distribution.id),
                'channel': Order.Channel.HALL,
                'guest_count': 4,
                'note': '',
            }
        )

        response = self.client.post(f"/api/v1/pos/billing/orders/{empty_order['id']}/prebill/print/", {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_rejects_closed_order(self):
        self.configure_live_printer()
        self.submit_order_via_api(self.order_id)
        self.pay_order_via_api(self.order_id, amount=66000)

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_requires_live_printer_configuration_falls_back_to_client_print(self):
        IntegrationConfig.objects.filter(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PRINTER).delete()

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['result']['code'], 'PRINTER_NOT_CONFIGURED')
        self.assertTrue(response.data['result']['requires_client_print'])

    def test_requires_printer_name_in_live_configuration_falls_back_to_client_print(self):
        printer = self.configure_live_printer(printer_name='')
        self.cash_desk.printer_integration = printer
        self.cash_desk.save(update_fields=['printer_integration', 'updated_at'])
        self.create_cash_shift(cash_desk=self.cash_desk)

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['result']['code'], 'PRINTER_NOT_CONFIGURED')
