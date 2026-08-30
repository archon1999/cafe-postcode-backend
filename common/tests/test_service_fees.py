from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from common.service_fees import (
    calculate_hourly_service_fee,
    calculate_service_fee_components,
    service_fee_billable_minutes,
)


class ServiceFeeCalculatorTests(SimpleTestCase):
    def test_hourly_rate_for_ninety_minutes(self):
        self.assertEqual(
            calculate_hourly_service_fee(hourly_rate=100_000, minutes=90),
            150_000,
        )

    def test_duration_is_rounded_down_to_complete_five_minute_blocks(self):
        started_at = timezone.now()
        for duration, expected in (
            (timedelta(0), 60),
            (timedelta(minutes=5), 60),
            (timedelta(minutes=55), 60),
            (timedelta(minutes=60), 60),
            (timedelta(minutes=60, seconds=1), 60),
            (timedelta(minutes=64, seconds=59), 60),
            (timedelta(minutes=65), 65),
            (timedelta(minutes=91), 90),
            (timedelta(minutes=94, seconds=59), 90),
            (timedelta(minutes=95), 95),
        ):
            with self.subTest(duration=duration):
                self.assertEqual(
                    service_fee_billable_minutes(
                        started_at=started_at,
                        ended_at=started_at + duration,
                    ),
                    expected,
                )

    def test_hourly_amount_is_rounded_to_thousands_with_half_ties_down(self):
        self.assertEqual(
            calculate_hourly_service_fee(hourly_rate=66_000, minutes=15),
            16_000,
        )
        self.assertEqual(
            calculate_hourly_service_fee(hourly_rate=66_004, minutes=15),
            17_000,
        )

    def test_percentage_and_hourly_components_are_additive(self):
        started_at = timezone.now()
        components = calculate_service_fee_components(
            snapshot=[
                {"scope": "restaurant", "mode": "percentage", "percent": 10},
                {"scope": "hall", "mode": "percentage", "percent": 3},
                {"scope": "table", "mode": "hourly", "hourly_rate": 100_000},
            ],
            subtotal=30_000,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=90),
        )

        self.assertEqual([row["amount"] for row in components], [3_000, 900, 150_000])
        self.assertEqual(components[-1]["duration_minutes"], 90)
