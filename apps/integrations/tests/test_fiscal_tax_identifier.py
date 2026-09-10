from types import SimpleNamespace
from unittest import TestCase

from apps.integrations.services.fiscal_drive_receipt_payload import FiscalDriveReceiptPayloadMixin
from apps.integrations.services.fiscal_drive_types import FiscalDriveError


class FiscalTaxIdentifierTests(TestCase):
    def test_quick_setup_validates_the_same_single_field(self):
        from apps.restaurants.api.admin.serializers.setup import SetupIntegrationSerializer

        for value, valid in [('123456789', True), ('33112976090034', True), ('123', False)]:
            serializer = SetupIntegrationSerializer(data={
                'name': 'Fiscal', 'provider': 'fiscal-drive-service', 'settings': {'taxNumber': value},
            })
            with self.subTest(value=value):
                self.assertEqual(serializer.is_valid(), valid, serializer.errors)

    def test_single_field_maps_identifier_without_changing_it(self):
        service = FiscalDriveReceiptPayloadMixin()
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='123456789'))
        payment = SimpleNamespace(method='cash', Method=SimpleNamespace(QR='qr'))
        for value, expected in [
            (' 33112976090034 ', {'PINFL': '33112976090034'}),
            ('001234567', {'TIN': '001234567'}),
            ('', {'TIN': '123456789'}),
        ]:
            service.settings = {'tax_number': value}
            with self.subTest(value=value):
                self.assertEqual(service._extra_info(order=order, payment=payment), expected)

    def test_invalid_identifier_is_rejected_and_qr_reference_is_preserved(self):
        service = FiscalDriveReceiptPayloadMixin()
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number=''))
        payment = SimpleNamespace(method='qr', external_ref='payment-1', Method=SimpleNamespace(QR='qr'))
        for value in ['123', '12345678x', '１２３４５６７８９', '1234567890123']:
            service.settings = {'taxNumber': value}
            with self.subTest(value=value), self.assertRaises(FiscalDriveError):
                service._extra_info(order=order, payment=payment)
        service.settings = {'taxNumber': '33112976090034'}
        self.assertEqual(service._extra_info(order=order, payment=payment), {
            'PINFL': '33112976090034', 'QRPaymentID': 'payment-1',
        })
