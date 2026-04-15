from unittest.mock import patch

from rest_framework import status

from apps.billing.models import Receipt
from apps.integrations.models import IntegrationConfig
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


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
        IntegrationConfig.objects.update_or_create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            defaults={
                'mode': IntegrationConfig.Mode.LIVE,
                'is_enabled': True,
                'settings': {
                    'printer_name': printer_name,
                    'paper_width_mm': 80,
                    'cut_after_print': True,
                    'encoding': 'cp437',
                },
            },
        )

    def configure_qz_printer(self, *, connection_type='system_printer', printer_name='POS-80 USB', host=''):
        settings = {
            'connection_type': connection_type,
            'paper_width_mm': 80,
            'cut_after_print': True,
            'encoding': 'cp437',
        }
        if connection_type == 'socket':
            settings.update({'host': host, 'port': 9100})
        else:
            settings['printer_name'] = printer_name

        IntegrationConfig.objects.update_or_create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='qz-tray',
            defaults={
                'mode': IntegrationConfig.Mode.LIVE,
                'is_enabled': True,
                'settings': settings,
            },
        )

    def test_open_hall_order_prints_prebill_and_creates_receipt(self):
        self.configure_live_printer()

        with patch(
            'apps.integrations.services.WindowsRawPrinterIntegrationService.print_prebill',
            return_value={
                'ok': True,
                'provider': 'windows-raw',
                'mode': 'live',
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

    def test_qz_tray_prebill_returns_client_print_job(self):
        self.configure_qz_printer()

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['receipt']['kind'], Receipt.Kind.PREBILL)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.CREATED)
        self.assertEqual(response.data['result']['provider'], 'qz-tray')
        self.assertTrue(response.data['result']['requires_client_print'])
        self.assertEqual(response.data['result']['print_job']['config']['printer_name'], 'POS-80 USB')
        self.assertEqual(response.data['result']['print_job']['flavor'], 'hex')
        self.assertIn('data', response.data['result']['print_job'])

        receipt = Receipt.objects.get(pk=response.data['receipt']['id'])
        self.assertEqual(receipt.status, Receipt.Status.CREATED)
        self.assertEqual(receipt.payload['snapshot']['order_number'], response.data['result']['order_number'])

    def test_qz_tray_print_result_callback_marks_receipt_sent(self):
        self.configure_qz_printer()
        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')
        receipt_id = response.data['receipt']['id']

        callback = self.client.post(
            f'/api/v1/pos/billing/receipts/{receipt_id}/print-result/',
            {'result': {'ok': True, 'provider': 'qz-tray', 'detail': 'printed by QZ Tray'}},
            format='json',
        )

        self.assertEqual(callback.status_code, status.HTTP_200_OK, callback.data)
        self.assertEqual(callback.data['receipt']['status'], Receipt.Status.SENT)
        receipt = Receipt.objects.get(pk=receipt_id)
        self.assertEqual(receipt.status, Receipt.Status.SENT)
        self.assertEqual(receipt.payload['client_result']['detail'], 'printed by QZ Tray')

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

    def test_requires_live_printer_configuration(self):
        IntegrationConfig.objects.filter(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PRINTER).delete()

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Live printer integration is not configured.')

    def test_requires_printer_name_in_live_configuration(self):
        self.configure_live_printer(printer_name='')

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Printer name is not configured for the live printer integration.')

    def test_qz_tray_requires_printer_name_for_system_printer(self):
        self.configure_qz_printer(printer_name='')

        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order_id}/prebill/print/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'QZ Tray printer name is not configured.')
