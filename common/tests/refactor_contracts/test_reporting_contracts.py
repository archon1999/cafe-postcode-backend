from datetime import datetime

from django.http import QueryDict
from django.test import TestCase

from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.dashboard.services.owner_dashboard_overview import OwnerDashboardBaseService
from apps.reporting.selectors.reporting import build_summary_payload, get_report_period
from apps.reporting.services.export_localization import get_summary_metrics
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from common.utils.date import TASHKENT_TIMEZONE


class ReportingContractCharacterizationTests(TestCase):
    @staticmethod
    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 4, 7, hour, minute, tzinfo=TASHKENT_TIMEZONE)

    @staticmethod
    def create_order(*, restaurant, number, status, total, closed_at=None):
        return Order.objects.create(
            restaurant=restaurant,
            order_number=number,
            channel=Order.Channel.TAKEAWAY,
            status=status,
            subtotal=total,
            total=total,
            closed_at=closed_at,
        )

    @staticmethod
    def stamp_created_at(instance, value):
        instance.__class__.objects.filter(pk=instance.pk).update(
            created_at=value, updated_at=value
        )
        instance.refresh_from_db()
        return instance

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="Reporting contract")
        self.other_restaurant = Restaurant.objects.create(
            name="Other reporting contract"
        )
        self.period = get_report_period(
            QueryDict("period_type=range&start_date=2026-04-07&end_date=2026-04-07")
        )

        closed_order = self.create_order(
            restaurant=self.restaurant,
            number=1,
            status=Order.Status.CLOSED,
            total=10_000,
            closed_at=self.at(12),
        )
        payment = Payment.objects.create(
            order=closed_order,
            method=Payment.Method.CASH,
            amount=10_000,
            status=Payment.Status.SUCCEEDED,
            paid_at=self.at(12, 1),
        )
        PaymentRefund.objects.create(
            payment=payment,
            amount=2_000,
            status=PaymentRefund.Status.SUCCEEDED,
            refunded_at=self.at(12, 2),
        )
        for kind, minute in ((Receipt.Kind.PLAIN, 3), (Receipt.Kind.FISCAL, 4)):
            receipt = Receipt.objects.create(
                order=closed_order, payment=payment, kind=kind
            )
            self.stamp_created_at(receipt, self.at(12, minute))

        open_order = self.create_order(
            restaurant=self.restaurant,
            number=2,
            status=Order.Status.SUBMITTED,
            total=3_000,
        )
        self.stamp_created_at(open_order, self.at(13))

        other_order = self.create_order(
            restaurant=self.other_restaurant,
            number=1,
            status=Order.Status.CLOSED,
            total=99_000,
            closed_at=self.at(14),
        )
        Payment.objects.create(
            order=other_order,
            method=Payment.Method.CARD,
            amount=99_000,
            status=Payment.Status.SUCCEEDED,
            paid_at=self.at(14, 1),
        )

        boundary_order = self.create_order(
            restaurant=self.restaurant,
            number=3,
            status=Order.Status.CLOSED,
            total=50_000,
            closed_at=self.period.end,
        )
        Payment.objects.create(
            order=boundary_order,
            method=Payment.Method.CARD,
            amount=50_000,
            status=Payment.Status.SUCCEEDED,
            paid_at=self.period.end,
        )

    def test_admin_export_and_dashboard_share_scoped_summary_semantics(self):
        admin_summary = build_summary_payload(self.restaurant, self.period)
        dashboard_summary = OwnerDashboardBaseService().build_dashboard_summary(
            self.restaurant,
            self.period,
        )

        self.assertEqual(
            admin_summary,
            {
                "gross_sales_total": 10_000,
                "refunds_total": 2_000,
                "sales_total": 8_000,
                "orders_count": 1,
                "average_check": 8_000,
                "prechecks_count": 1,
                "receipts_count": 1,
            },
        )
        self.assertEqual(
            {key: dashboard_summary[key] for key in admin_summary},
            admin_summary,
        )
        self.assertEqual(dashboard_summary["open_checks"], 1)
        self.assertEqual(dashboard_summary["active_tables"], 0)
        self.assertEqual(
            [value for _label, value in get_summary_metrics(admin_summary)],
            [10_000, 2_000, 8_000, 1, 8_000, 1, 1],
        )

    def test_range_uses_inclusive_tashkent_dates_and_exclusive_end_instant(self):
        self.assertEqual(self.period.start, self.at(0))
        self.assertEqual(
            self.period.end, datetime(2026, 4, 8, tzinfo=TASHKENT_TIMEZONE)
        )
        self.assertEqual(self.period.value, "2026-04-07 - 2026-04-07")
        self.assertEqual(self.period.file_label, "range-2026-04-07-to-2026-04-07")
