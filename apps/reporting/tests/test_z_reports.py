from datetime import timedelta
from io import BytesIO

from django.utils import timezone
from openpyxl import load_workbook

from apps.billing.models import FiscalShiftSession
from apps.reporting.selectors.z_reports import build_z_report_row
from apps.sales.tests.support.pos_api import PosAPITestCase
from common.utils.date import TASHKENT_TIMEZONE


class ZReportTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        now = timezone.localtime(timezone.now(), TASHKENT_TIMEZONE).replace(hour=12)
        self.params = {'startDate': now.date().isoformat(), 'endDate': now.date().isoformat()}
        self.session = FiscalShiftSession.objects.create(
            restaurant=self.restaurant, cash_desk=self.cash_desk, closed_by=self.user,
            opened_at=now - timedelta(days=1), closed_at=now, status='closed', terminal_id='TERM-Z',
            close_payload={'provider_result': {'provider_report': {'z_info': {
                'TotalCash': {'Sale': 125050, 'Refund': 10000},
                'TotalCard': {'Sale': 50000, 'Refund': 0},
                'TotalSaleCount': 3, 'TotalRefundCount': 1,
            }}}},
        )

    def test_list_scopes_by_restaurant_closed_status_and_close_date(self):
        other = self.restaurant.__class__.objects.create(name='Other Z restaurant')
        for restaurant, status, closed_at in [
            (other, 'closed', self.session.closed_at),
            (self.restaurant, 'open', None),
            (self.restaurant, 'closed', self.session.closed_at - timedelta(days=2)),
        ]:
            FiscalShiftSession.objects.create(
                restaurant=restaurant, status=status, opened_at=self.session.opened_at,
                closed_at=closed_at,
            )
        response = self.client.get('/api/v1/admin/reporting/z-reports/', self.params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        row = response.data['data'][0]
        self.assertEqual(row['id'], str(self.session.id))
        self.assertEqual(row['sale_total'], 1750.5)
        self.assertEqual(row['refund_total'], 100)
        self.assertIsNone(row['qr_total'])

    def test_search_cash_desk_and_export_use_same_rows(self):
        params = {**self.params, 'cashDeskId': str(self.cash_desk.id), 'search': 'TERM-Z'}
        response = self.client.get('/api/v1/admin/reporting/z-reports/', params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        exported = self.client.get('/api/v1/admin/reporting/z-reports/export/', params)
        self.assertEqual(exported.status_code, 200)
        values = list(load_workbook(BytesIO(exported.content)).active.values)
        self.assertTrue(any('TERM-Z' in row and 1750.5 in row for row in values))
        for change in ({'search': 'missing'}, {'cashDeskId': 'invalid'}):
            response = self.client.get('/api/v1/admin/reporting/z-reports/', {**params, **change})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 0)

    def test_missing_or_malformed_evidence_is_not_zero(self):
        for payload in ({}, {'provider_result': []}, {'provider_result': {'provider_report': {'z_info': {
            'TotalCash': [], 'TotalSaleAmount': 'NaN', 'TotalRefundAmount': 'invalid',
        }}}}):
            self.session.close_payload = payload
            row = build_z_report_row(self.session)
            self.assertIsNone(row['sale_total'])
            self.assertIsNone(row['refund_total'])

    def test_reports_permission_is_required(self):
        self.role.permissions.clear()
        for path in ('z-reports/', 'z-reports/export/'):
            response = self.client.get('/api/v1/admin/reporting/' + path, self.params)
            self.assertEqual(response.status_code, 403)
