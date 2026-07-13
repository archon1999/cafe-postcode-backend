from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.printing.services.documents import _channel_label, _payment_method_label


class PrintDocumentChannelLabelTests(SimpleTestCase):
    def test_receipt_channel_labels_use_requested_latin_text(self):
        self.assertEqual(_channel_label(SimpleNamespace(channel='hall')), 'Zal')
        self.assertEqual(_channel_label(SimpleNamespace(channel='takeaway')), 'Soboy')
        self.assertEqual(_channel_label(SimpleNamespace(channel='delivery')), 'Dostavka')

    def test_payment_method_uses_receipt_label(self):
        self.assertEqual(_payment_method_label('cash'), 'Naqd')
        self.assertEqual(_payment_method_label('card'), 'Karta')
        self.assertEqual(_payment_method_label('mixed'), 'Aralash')
