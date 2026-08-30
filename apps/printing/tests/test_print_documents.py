from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.printing.services.documents import _channel_label, _payment_method_label
from apps.printing.services.print_snapshots import _print_item_values, _service_fee_totals


class PrintDocumentChannelLabelTests(SimpleTestCase):
    def test_hourly_service_fee_snapshot_uses_hourly_label_without_rate(self):
        order = SimpleNamespace(
            service_fee_percent=0,
            get_service_fee_components=lambda as_of=None: [
                {
                    'scope': 'table',
                    'mode': 'hourly',
                    'hourly_rate': 100_000,
                    'duration_minutes': 65,
                    'amount': 108_000,
                }
            ],
        )

        totals = _service_fee_totals(order)

        self.assertEqual(totals['tableServiceFeeRateLabel'], 'Soatlik')

    def test_receipt_channel_labels_use_requested_latin_text(self):
        self.assertEqual(_channel_label(SimpleNamespace(channel='hall')), 'Zal')
        self.assertEqual(_channel_label(SimpleNamespace(channel='takeaway')), 'Soboy')
        self.assertEqual(_channel_label(SimpleNamespace(channel='delivery')), 'Dostavka')

    def test_payment_method_uses_receipt_label(self):
        self.assertEqual(_payment_method_label('cash'), 'Naqd')
        self.assertEqual(_payment_method_label('card'), 'Karta')
        self.assertEqual(_payment_method_label('mixed'), 'Aralash')

    def test_item_snapshot_keeps_modifiers_above_the_item_note(self):
        modifiers = [
            SimpleNamespace(
                modifier_option_id='option-1',
                group_name='Shakar miqdori',
                option_name='Shakarsiz',
                price_delta=0,
            ),
            SimpleNamespace(
                modifier_option_id='option-2',
                group_name='Ichimlik harorati',
                option_name='Muzsiz',
                price_delta=0,
            ),
        ]
        item = SimpleNamespace(
            catalog_item_id='item-1',
            catalog_item=SimpleNamespace(name='Limonad'),
            name_snapshot='',
            unit_price=29000,
            note='Limon qo‘shmang',
            modifiers=SimpleNamespace(all=lambda: modifiers),
        )

        values, _, item_note = _print_item_values(item)

        self.assertEqual(
            values['modifierText'],
            'Shakar miqdori: Shakarsiz\nIchimlik harorati: Muzsiz',
        )
        self.assertEqual(values['note'], 'Limon qo‘shmang')
        self.assertEqual(item_note, 'Limon qo‘shmang')
