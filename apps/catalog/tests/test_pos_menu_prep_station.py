from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import translation
from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import (
    CatalogCategory,
    CatalogItem,
    CatalogItemGroup,
    CatalogItemGroupMember,
)
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.catalog.views.pos_menu import PosMenuView
from apps.restaurants.models import PrepStation, Restaurant
from apps.users.models import User


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class PosMenuPrepStationTests(APITestCase):
    menu_url = '/api/v1/pos/catalog/menu/'

    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Prep station menu restaurant')
        cls.user = User.objects.create_superuser(
            username='prep-station-menu-admin',
            password='secret123',
            restaurant=cls.restaurant,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Menu category',
        )
        cls.items = [
            CatalogItem.objects.create(
                restaurant=cls.restaurant,
                category=cls.category,
                name=f'Menu item {index}',
                price=10_000 + index,
                sort_order=index,
            )
            for index in range(3)
        ]
        cls.group = CatalogItemGroup.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Menu variants',
        )
        CatalogItemGroupMember.objects.bulk_create(
            [
                CatalogItemGroupMember(
                    group=cls.group,
                    catalog_item=item,
                    variant_name=f'Variant {index}',
                    sort_order=index,
                )
                for index, item in enumerate(cls.items[:2])
            ]
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
        # Keep request scope lookup out of the query-count assertions.
        profile = self.user.restaurant_profile
        _ = profile.restaurant

    def tearDown(self):
        translation.activate('uz')
        super().tearDown()

    def _get_menu_category(self):
        response = self.client.get(self.menu_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        payload = response.data.get('data', response.data)
        return next(row for row in payload if row['id'] == str(self.category.id))

    def _get_menu_response(self, **headers):
        response = self.client.get(self.menu_url, **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response

    def _serialize_reference_menu(self):
        """Serialize the same graph without the request-level fallback shortcut."""
        view = PosMenuView()
        view._restaurant = self.restaurant
        categories = view.get_queryset()
        return CatalogMenuCategorySerializer(categories, many=True).data

    def _assert_item_station(self, item_payload, station):
        expected_id = str(station.id) if station is not None else None
        expected_name = station.name if station is not None else ''
        self.assertEqual(item_payload['prep_station'], expected_id)
        self.assertEqual(item_payload['prep_station_name'], expected_name)

    def _assert_all_item_paths_use_station(self, category_payload, station):
        for item_payload in category_payload['items']:
            self._assert_item_station(item_payload, station)
        for group_payload in category_payload['item_groups']:
            for member_payload in group_payload['members']:
                self._assert_item_station(member_payload['item'], station)

    @staticmethod
    def _fallback_query_count(captured_queries):
        return sum(
            ' from "restaurants_prepstation"' in query['sql'].lower()
            for query in captured_queries
        )

    def test_menu_fallback_semantics_for_zero_one_and_multiple_active_stations(self):
        PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Inactive station',
            is_active=False,
        )

        with self.subTest(active_station_count=0):
            self._assert_all_item_paths_use_station(self._get_menu_category(), None)

        first_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Only active station',
        )
        with self.subTest(active_station_count=1):
            self._assert_all_item_paths_use_station(
                self._get_menu_category(),
                first_station,
            )

        PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Second active station',
        )
        with self.subTest(active_station_count=2):
            self._assert_all_item_paths_use_station(self._get_menu_category(), None)

    def test_explicit_item_and_category_stations_keep_precedence_over_fallback(self):
        fallback_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Fallback station',
        )
        item_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Item station',
            is_active=False,
        )
        category_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Category station',
            is_active=False,
        )

        item = self.items[2]
        item.prep_station = item_station
        item.save(update_fields=['prep_station', 'updated_at'])

        category_payload = self._get_menu_category()
        direct_item = next(row for row in category_payload['items'] if row['id'] == str(item.id))
        self._assert_item_station(direct_item, item_station)

        self.category.prep_station = category_station
        self.category.save(update_fields=['prep_station', 'updated_at'])
        category_payload = self._get_menu_category()
        self._assert_all_item_paths_use_station(category_payload, category_station)

        self.assertNotEqual(fallback_station.id, item_station.id)

    def test_menu_query_count_does_not_grow_with_items_or_group_members(self):
        query_counts = []

        for active_station_count in (0, 1, 2):
            with self.subTest(active_station_count=active_station_count):
                PrepStation.objects.filter(restaurant=self.restaurant).delete()
                PrepStation.objects.bulk_create(
                    [
                        PrepStation(
                            restaurant=self.restaurant,
                            name=f'Active station {index}',
                        )
                        for index in range(active_station_count)
                    ]
                )

                with CaptureQueriesContext(connection) as small_context:
                    self._get_menu_category()

                extra_items = CatalogItem.objects.bulk_create(
                    [
                        CatalogItem(
                            restaurant=self.restaurant,
                            category=self.category,
                            name=f'Extra menu item {active_station_count}-{index}',
                            price=20_000 + index,
                            sort_order=100 + index,
                        )
                        for index in range(18)
                    ]
                )
                CatalogItemGroupMember.objects.bulk_create(
                    [
                        CatalogItemGroupMember(
                            group=self.group,
                            catalog_item=item,
                            variant_name=f'Extra variant {index}',
                            sort_order=100 + index,
                        )
                        for index, item in enumerate(extra_items[:9])
                    ]
                )

                with CaptureQueriesContext(connection) as large_context:
                    self._get_menu_category()

                small_count = len(small_context)
                large_count = len(large_context)
                query_counts.append(small_count)
                self.assertEqual(large_count, small_count)
                self.assertLessEqual(large_count, 14)
                self.assertEqual(
                    self._fallback_query_count(small_context.captured_queries),
                    1,
                )
                self.assertEqual(
                    self._fallback_query_count(large_context.captured_queries),
                    1,
                )

                CatalogItem.objects.filter(id__in=[item.id for item in extra_items]).delete()

        self.assertEqual(len(set(query_counts)), 1)

    def test_optimized_payload_matches_reference_resolution_in_every_language(self):
        PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Fallback station',
        )
        self.items[0].name_uz = 'Lotincha nom'
        self.items[0].description_uz = 'Lotincha tavsif'
        self.items[0].name_uz_crl = 'Кириллча ном'
        self.items[0].description_uz_crl = 'Кириллча тавсиф'
        self.items[0].name_ru = 'Русское название'
        self.items[0].description_ru = 'Русское описание'
        self.items[0].save()

        for language in ('uz', 'uz-crl', 'ru'):
            with self.subTest(language=language):
                response = self._get_menu_response(HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(
                    response.data.get('data', response.data),
                    self._serialize_reference_menu(),
                )

    def test_item_prefetch_queries_load_modeltranslation_fields(self):
        with CaptureQueriesContext(connection) as captured:
            self._get_menu_response(HTTP_ACCEPT_LANGUAGE='ru')

        catalog_item_queries = [
            query['sql'].lower()
            for query in captured.captured_queries
            if ' from "catalog_catalogitem"' in query['sql'].lower()
        ]
        self.assertTrue(catalog_item_queries)
        for sql in catalog_item_queries:
            for field in (
                'name_uz',
                'name_uz_crl',
                'name_ru',
                'description_uz',
                'description_uz_crl',
                'description_ru',
            ):
                self.assertIn(f'"{field}"', sql)
