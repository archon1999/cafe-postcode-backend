from datetime import UTC, datetime

from django.test import SimpleTestCase

from common.utils.date import (
    EDate,
    EDateTime,
    TASHKENT_TIMEZONE,
    as_edate,
    as_edatetime,
    localize_to_tashkent,
    tashkent_day_bounds,
)


class DateUtilsTests(SimpleTestCase):
    def test_edate_uses_renamed_boundary_methods(self):
        value = EDate(2026, 3, 28)

        self.assertEqual(value.to_datetime(), EDateTime(2026, 3, 28, 0, 0))
        self.assertEqual(value.start_of_month(), EDate(2026, 3, 1))
        self.assertEqual(value.end_of_month(), EDate(2026, 3, 31))
        self.assertEqual(value.start_of_previous_month(), EDate(2026, 2, 1))
        self.assertEqual(value.end_of_previous_year(), EDate(2025, 12, 31))

    def test_edatetime_uses_renamed_boundary_methods(self):
        value = EDateTime(2026, 3, 28, 14, 25, 40, 123456, tzinfo=TASHKENT_TIMEZONE)

        self.assertEqual(value.start_of_day(), EDateTime(2026, 3, 28, 0, 0, 0, 0, tzinfo=TASHKENT_TIMEZONE))
        self.assertEqual(
            value.end_of_hour(),
            EDateTime(2026, 3, 28, 14, 59, 59, 999999, tzinfo=TASHKENT_TIMEZONE),
        )
        self.assertEqual(value.next_hour(), EDateTime(2026, 3, 28, 15, 25, 40, 123456, tzinfo=TASHKENT_TIMEZONE))
        self.assertEqual(
            value.start_of_previous_year(),
            EDateTime(2025, 1, 1, 14, 25, 40, 123456, tzinfo=TASHKENT_TIMEZONE),
        )

    def test_tashkent_helpers_convert_utc_inputs(self):
        utc_value = datetime(2026, 3, 27, 20, 15, tzinfo=UTC)

        localized_value = localize_to_tashkent(utc_value)
        start, end = tashkent_day_bounds(localized_value)

        self.assertEqual(localized_value, as_edatetime(datetime(2026, 3, 28, 1, 15, tzinfo=TASHKENT_TIMEZONE)))
        self.assertEqual(start, as_edatetime(datetime(2026, 3, 28, 0, 0, tzinfo=TASHKENT_TIMEZONE)))
        self.assertEqual(end, as_edatetime(datetime(2026, 3, 29, 0, 0, tzinfo=TASHKENT_TIMEZONE)))
        self.assertEqual(as_edate(localized_value), EDate(2026, 3, 28))
