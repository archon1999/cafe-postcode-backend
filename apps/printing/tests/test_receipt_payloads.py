from copy import deepcopy

from django.test import SimpleTestCase

from apps.printing.services.documents import build_legacy_receipt_payload
from apps.printing.services.receipt_payloads import build_legacy_receipt_payload as extracted_payload_normalizer


class LegacyReceiptPayloadTests(SimpleTestCase):
    def test_documents_module_keeps_the_legacy_import_surface(self):
        self.assertIs(build_legacy_receipt_payload, extracted_payload_normalizer)

    def setUp(self):
        self.snapshot = {
            'restaurant': {
                'name': 'Qamish Gamburg',
                'legalName': 'QAMISH GAMBURG MCHJ',
                'address': "Toshkent, Qamish ko'chasi 1",
                'phone': '+998 90 000 00 00',
                'social': '@qamish',
                'taxNumber': '312217845',
            },
            'order': {
                'id': 'order-1',
                'displayNumber': '704',
                'channel': 'hall',
                'channelLabel': 'Zal',
                'table': 'Stol 7',
                'waiter': 'Vali',
                'cashier': 'Ali',
                'note': 'Piyozsiz',
            },
            'items': [
                {
                    'name': 'Osh',
                    'quantity': 2,
                    'unitPrice': 30000,
                    'lineTotal': 60000,
                    'note': 'Achchiq',
                    'vat': 6428,
                    'vatPercent': 12,
                }
            ],
            'payment': {
                'method': 'Aralash',
                'amount': 66000,
                'cash': 40000,
                'card': 26000,
                'change': 0,
                'paidAt': '2026-07-15 10:20:30',
            },
            'totals': {
                'subtotal': 60000,
                'serviceFee': 6000,
                'vat': 7071,
                'total': 66000,
            },
        }

    def test_projects_the_exact_legacy_payload_and_preserves_only_unmanaged_fiscal_values(self):
        payload = build_legacy_receipt_payload(
            snapshot=self.snapshot,
            fiscal_result={
                'fiscal_receipt_number': 'F-704',
                'restaurant_name': 'stale restaurant',
                'amount': -1,
            },
        )

        self.assertEqual(
            payload,
            {
                'fiscal_receipt_number': 'F-704',
                'restaurant_name': 'Qamish Gamburg',
                'amount': 66000,
                'restaurant_legal_name': 'QAMISH GAMBURG MCHJ',
                'restaurant_address': "Toshkent, Qamish ko'chasi 1",
                'restaurant_phone': '+998 90 000 00 00',
                'restaurant_social': '@qamish',
                'tax_number': '312217845',
                'order_id': 'order-1',
                'order_number': '704',
                'order_label': '#704',
                'channel': 'hall',
                'channel_label': 'Zal',
                'table_label': 'Stol: Stol 7',
                'waiter_name': 'Vali',
                'cashier_name': 'Ali',
                'order_note': 'Piyozsiz',
                'items': [
                    {
                        'name': 'Osh',
                        'quantity': 2,
                        'unit_price': 30000,
                        'line_total': 60000,
                        'note': 'Achchiq',
                    }
                ],
                'subtotal': 60000,
                'service_fee': 6000,
                'vat_amount': 7071,
                'total': 66000,
                'payment_method': 'Aralash',
                'cash_amount': 40000,
                'card_amount': 26000,
                'change': 0,
                'paid_at': '2026-07-15 10:20:30',
            },
        )

    def test_uses_an_empty_table_label_without_mutating_the_snapshot(self):
        snapshot = deepcopy(self.snapshot)
        snapshot['order']['table'] = ''
        original = deepcopy(snapshot)

        payload = build_legacy_receipt_payload(snapshot=snapshot)

        self.assertEqual(payload['table_label'], '')
        self.assertEqual(snapshot, original)
