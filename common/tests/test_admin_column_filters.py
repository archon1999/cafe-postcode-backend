import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.apps import apps
from django.test import TestCase, SimpleTestCase
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from common.api.column_filters import AdminColumnFilterBackend, FILTER_SCHEMAS, apply_column_filters
from common.api.paginations import Pagination


def payload(field, operator, *values):
    return json.dumps([{'field': field, 'operator': operator, 'values': list(values)}])


class AdminColumnFilterContractTests(SimpleTestCase):
    def test_all_allowlisted_lookups_are_real_model_fields(self):
        for schema in FILTER_SCHEMAS.values():
            for definition in schema['fields'].values():
                model = apps.get_model(schema['model'])
                for part in definition['lookup'].split('__'):
                    field = model._meta.get_field(part)
                    model = field.related_model if field.is_relation else model

    def test_rejects_unknown_fields_operators_and_invalid_values(self):
        samples = [
            'null', '{}', 'not-json', '[null]',
            payload('opened_by__password', 'contains', 'x'),
            payload('status', 'contains', 'open'),
            payload('status', 'equals', 'invented'),
            payload('itemsAndTotal', 'equals', 'NaN'),
            payload('itemsAndTotal', 'equals', 'Infinity'),
            payload('itemsAndTotal', 'between', '100', '1'),
            payload('createdAt', 'equals', '2026-02-30'),
            payload('orderNumber', 'equals'),
            payload('orderNumber', 'regex', '.*'),
            payload('orderNumber', 'equals', '1')[:-1] + ',' + payload('orderNumber', 'equals', '2')[1:],
        ]
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(ValidationError):
                apply_column_filters(Order.objects.all(), sample)

    def test_pos_and_detail_requests_cannot_use_admin_filter_contract(self):
        for path, kwargs in [('/api/v1/pos/orders/', {}), ('/api/v1/admin/sales/orders/1/', {'pk': '1'})]:
            request = SimpleNamespace(method='GET', path=path, query_params={'columnFilters': payload('orderNumber', 'equals', '1')})
            with self.assertRaises(ValidationError):
                AdminColumnFilterBackend().filter_queryset(request, Order.objects.all(), SimpleNamespace(kwargs=kwargs))


class RowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ('id', 'order_number', 'total', 'status')


class ScopedList(generics.ListAPIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = RowSerializer
    pagination_class = Pagination
    filter_backends = [AdminColumnFilterBackend]

    def get_queryset(self):
        return Order.objects.filter(restaurant_id=self.kwargs['restaurant_id']).order_by('order_number')


class AdminColumnFilterQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Filter scope')
        cls.other = Restaurant.objects.create(name='Other scope')
        Order.objects.bulk_create([
            Order(restaurant=cls.restaurant, order_number=index, total=index * 1000, status='open' if index % 2 else 'closed')
            for index in range(1, 26)
        ] + [Order(restaurant=cls.other, order_number=100, total=15000, status='open')])

    def test_filter_is_applied_before_pagination_and_preserves_scope(self):
        request = APIRequestFactory().get('/api/v1/admin/sales/orders/', {
            'column_filters': payload('itemsAndTotal', 'gte', '15000'), 'page_size': 3, 'page': 2,
        })
        response = ScopedList.as_view()(request, restaurant_id=self.restaurant.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 11)
        self.assertEqual([row['order_number'] for row in response.data['data']], [18, 19, 20])

    def test_multiple_filters_are_anded_and_range_is_inclusive(self):
        raw = json.dumps([
            {'field': 'itemsAndTotal', 'operator': 'between', 'values': ['10000', '15000']},
            {'field': 'status', 'operator': 'in', 'values': ['open']},
        ])
        rows = apply_column_filters(Order.objects.filter(restaurant=self.restaurant), raw)
        self.assertEqual(list(rows.order_by('order_number').values_list('order_number', flat=True)), [11, 13, 15])

    def test_relation_text_and_not_equal(self):
        rows = apply_column_filters(Order.objects.all(), payload('restaurantName', 'contains', 'filter'))
        self.assertEqual(rows.count(), 25)
        rows = apply_column_filters(rows, payload('status', 'not_equal', 'closed'))
        self.assertEqual(rows.count(), 13)

    def test_date_uses_local_day(self):
        Order.objects.filter(restaurant=self.restaurant, order_number=1).update(created_at=datetime(2026, 10, 22, 20, tzinfo=ZoneInfo('UTC')))
        with self.settings(TIME_ZONE='Asia/Tashkent'):
            rows = apply_column_filters(Order.objects.filter(order_number=1), payload('createdAt', 'equals', '2026-10-23'))
            self.assertEqual(rows.count(), 1)

    def test_invalid_filters_return_400_instead_of_silently_ignoring(self):
        request = APIRequestFactory().get('/api/v1/admin/sales/orders/', {'columnFilters': payload('password', 'equals', 'x')})
        response = ScopedList.as_view()(request, restaurant_id=self.restaurant.id)
        self.assertEqual(response.status_code, 400)
