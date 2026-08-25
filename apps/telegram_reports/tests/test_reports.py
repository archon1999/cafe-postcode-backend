from datetime import date

from django.test import SimpleTestCase

from apps.reporting.services import CommonReportService
from apps.telegram_reports.models import TelegramReportDelivery
from apps.telegram_reports.services import TelegramReportService
from apps.telegram_reports.formatters import split_telegram_message


class Branch:
    name = "Qamish"


class FakeCommonReportService(CommonReportService):
    last_build_kwargs = None

    def build(self, **kwargs):
        self.__class__.last_build_kwargs = kwargs
        period = kwargs["period"]
        return {
            "period": period,
            "summary": {"sales_total": 2_960_000, "orders_count": 74, "average_check": 40_000},
            "comparisons": {
                "sales_total": {"current": 2_960_000, "previous": 2_500_000, "difference": 460_000, "change_percent": 18.4},
                "orders_count": {"current": 74, "previous": 80, "difference": -6, "change_percent": -7.5},
                "average_check": {"current": 40_000, "previous": 31_250, "difference": 8_750, "change_percent": 28.0},
            },
            "top_items": [
                {"catalog_item_id": None, "item_name": "Burger", "category_id": None, "category_name": None, "quantity": 12, "revenue": 1_200_000}
            ],
            "daily_breakdown": [
                {
                    "date": date(2026, 7, 20 + offset),
                    "sales_total": 2_500_000 + offset * 100_000,
                    "sales_difference": 500_000 - offset * 100_000,
                }
                for offset in range(7)
            ],
        }


class TelegramReportTemplateTests(SimpleTestCase):
    def setUp(self):
        FakeCommonReportService.last_build_kwargs = None
        self.service = TelegramReportService()
        self.service.common_report_service_class = FakeCommonReportService

    def test_daily_report_uses_compact_money_and_branch_wording(self):
        period = CommonReportService.build_day_period(date(2026, 7, 24))
        text = self.service.render(
            restaurant=Branch(),
            report_type=TelegramReportDelivery.ReportType.DAILY,
            period=period,
        )

        self.assertIn("2,96 mln so‘m", text)
        self.assertIn("1,2 mln so‘m", text)
        self.assertIn("Qamish", text)
        self.assertNotIn("Restaurant", text)
        self.assertNotIn("TOP-5", text)
        self.assertIsNone(FakeCommonReportService.last_build_kwargs["top_item_limit"])

    def test_weekly_report_contains_monospaced_three_row_grid(self):
        period = CommonReportService.build_range_period(date(2026, 7, 20), date(2026, 7, 26))
        text = self.service.render(
            restaurant=Branch(),
            report_type=TelegramReportDelivery.ReportType.WEEKLY,
            period=period,
        )

        self.assertIn("<pre>", text)
        self.assertIn("Du 20", text)
        self.assertIn("+0,5", text)

    def test_current_week_period_runs_from_monday_through_today(self):
        period = self.service.build_current_period(
            TelegramReportDelivery.ReportType.WEEKLY,
            today=date(2026, 7, 23),
        )

        self.assertEqual(period.start.date(), date(2026, 7, 20))
        self.assertEqual(period.end.date(), date(2026, 7, 24))

    def test_current_month_period_uses_current_calendar_month(self):
        period = self.service.build_current_period(
            TelegramReportDelivery.ReportType.MONTHLY,
            today=date(2026, 7, 23),
        )

        self.assertEqual(period.start.date(), date(2026, 7, 1))
        self.assertEqual(period.end.date(), date(2026, 8, 1))

    def test_all_products_are_rendered_across_multiple_messages(self):
        class ManyItemsReportService(FakeCommonReportService):
            def build(self, **kwargs):
                report = super().build(**kwargs)
                report["top_items"] = [
                    {
                        "catalog_item_id": None,
                        "item_name": f"Mahsulot {index} {'x' * 180}",
                        "category_id": None,
                        "category_name": None,
                        "quantity": index,
                        "revenue": index * 10_000,
                    }
                    for index in range(1, 31)
                ]
                return report

        self.service.common_report_service_class = ManyItemsReportService
        period = CommonReportService.build_day_period(date(2026, 7, 24))

        messages = split_telegram_message(
            self.service.render(
                restaurant=Branch(),
                report_type=TelegramReportDelivery.ReportType.DAILY,
                period=period,
            )
        )

        self.assertGreater(len(messages), 1)
        rendered = "\n".join(messages)
        for index in range(1, 31):
            self.assertIn(f"Mahsulot {index} ", rendered)
