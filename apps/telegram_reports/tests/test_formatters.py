from datetime import date

from django.test import SimpleTestCase

from apps.telegram_reports.formatters import (
    TELEGRAM_MESSAGE_TEXT_LIMIT,
    build_weekly_grid,
    format_compact_money,
    format_mln_money,
    split_telegram_message,
)


class TelegramReportFormatterTests(SimpleTestCase):
    def test_compact_money_uses_requested_uzbek_units(self):
        self.assertEqual(format_compact_money(39_032), "39 ming so‘m")
        self.assertEqual(format_compact_money(2_960_000), "2,96 mln so‘m")
        self.assertEqual(format_compact_money(2_500_000), "2,5 mln so‘m")
        self.assertEqual(format_mln_money(500_000, signed=True), "+0,5")
        self.assertEqual(format_mln_money(-1_000_000, signed=True), "-1")

    def test_weekly_grid_has_three_equal_width_rows(self):
        rows = [
            {
                "date": date(2026, 7, 20 + index),
                "sales_total": value,
                "sales_difference": difference,
            }
            for index, (value, difference) in enumerate(
                (
                    (2_500_000, 500_000),
                    (2_700_000, -1_000_000),
                    (3_150_000, 200_000),
                    (2_900_000, -150_000),
                    (4_100_000, 800_000),
                    (3_850_000, 400_000),
                    (3_200_000, -300_000),
                )
            )
        ]

        grid = build_weekly_grid(rows)
        lines = grid.splitlines()

        self.assertEqual(len(lines), 3)
        self.assertEqual(len({len(line) for line in lines}), 1)
        self.assertIn("2,5", lines[1])
        self.assertIn("+0,5", lines[2])
        self.assertIn("-1", lines[2])

    def test_long_report_is_split_on_line_boundaries(self):
        text = "\n".join(f"{index}. {'x' * 220}" for index in range(30))

        messages = split_telegram_message(text)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= TELEGRAM_MESSAGE_TEXT_LIMIT for message in messages))
        self.assertEqual("\n".join(messages), text)
