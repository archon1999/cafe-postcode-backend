from apps.printing.models import PrintDocument, PrintTemplate
from apps.printing.services import create_shift_report_print_document
from apps.sales.tests.support.pos_api import PosTestCase


class ShiftReportPrintDocumentTests(PosTestCase):
    def test_creates_fixed_general_and_fiscal_shift_documents(self):
        shift = self.create_cash_shift()
        general_report = {
            'TerminalID': 'KASSA-1',
            'OpenTime': '2026-07-13 08:00:00',
            'TotalSaleCount': 2,
            'TotalRefundCount': 0,
            'TotalCash': {'Sale': 50000, 'Refund': 0},
            'TotalCard': {'Sale': 30000, 'Refund': 0},
            'TotalQR': {'Sale': 10000, 'Refund': 0},
            'TotalVAT': {'Sale': 9055, 'Refund': 0},
            'TotalSaleAmount': 90000,
            'Payments': [{'order_number': 10}, {'order_number': 11}],
        }
        fiscal_report = {
            **general_report,
            'FactoryID': 'FM-1',
            'SerialNumber': 'SN-1',
            'FirstReceiptSeq': 21,
            'LastReceiptSeq': 22,
        }

        general = create_shift_report_print_document(
            shift=shift,
            report=general_report,
            fiscal=False,
            closed=False,
            created_by=self.user,
        )
        fiscal = create_shift_report_print_document(
            shift=shift,
            report=fiscal_report,
            fiscal=True,
            closed=False,
            created_by=self.user,
        )

        self.assertEqual(general.kind, PrintTemplate.Kind.SHIFT_REPORT)
        self.assertEqual(fiscal.kind, PrintTemplate.Kind.SHIFT_REPORT)
        self.assertEqual(general.data_snapshot['report']['firstReceipt'], '10')
        self.assertEqual(general.data_snapshot['report']['vatSale'], 0)
        self.assertEqual(fiscal.data_snapshot['report']['firstReceipt'], '21')
        self.assertEqual(fiscal.data_snapshot['report']['cashSale'], 500)
        self.assertEqual(fiscal.data_snapshot['report']['vatSale'], 90.55)
        self.assertEqual(fiscal.data_snapshot['report']['totalSale'], 900)
        self.assertEqual(fiscal.data_snapshot['report']['factoryId'], 'FM-1')
        self.assertEqual(PrintDocument.objects.filter(source_id=shift.id).count(), 2)
