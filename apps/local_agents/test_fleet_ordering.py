from datetime import datetime
from types import SimpleNamespace

from django.test import TestCase

from apps.local_agents.admin_views import LocalAgentFleetListView
from apps.local_agents.models import LocalAgent
from apps.restaurants.models import Restaurant


class FleetOrderingTests(TestCase):
    def setUp(self):
        entries = [
            ('Zulu', '2.9.0', '2026-09-10T10:05:59+00:00'),
            ('Beta', '2.10.0', '2026-09-10T10:05:50+00:00'),
            ('Alpha', '2.10.0', '2026-09-10T10:05:01+00:00'),
            ('Older', '9.0.0', '2026-09-10T10:04:59+00:00'),
            ('Newest', '1.0.0', '2026-09-10T10:06:00+00:00'),
            ('Never seen', '20.0.0', None),
            ('No version', '', '2026-09-10T10:05:59+00:00'),
        ]
        for name, version, timestamp in entries:
            LocalAgent.objects.create(
                restaurant=Restaurant.objects.create(name=name),
                token_hash=name,
                version=version,
                last_seen_at=datetime.fromisoformat(timestamp) if timestamp else None,
            )

    def queryset(self, **params):
        view = LocalAgentFleetListView()
        view.request = SimpleNamespace(query_params=params)
        return view.get_queryset()

    def test_default_and_header_desc_order_by_minute_version_and_name_before_pagination(self):
        expected = ['Newest', 'Alpha', 'Beta', 'Zulu', 'No version', 'Older', 'Never seen']
        for ordering in ('', '-lastSeenAt'):
            with self.subTest(ordering=ordering):
                rows = self.queryset(ordering=ordering).values_list('restaurant__name', flat=True)
                self.assertEqual(list(rows), expected)
                self.assertEqual(list(rows[2:4]), expected[2:4])

    def test_search_and_manual_name_order_remain_available(self):
        rows = self.queryset(ordering='restaurantName', search='a').values_list('restaurant__name', flat=True)
        self.assertEqual(list(rows), ['Alpha', 'Beta'])

    def test_empty_fleet_does_not_break_ordering(self):
        self.assertEqual(list(self.queryset(search='does not exist')), [])
