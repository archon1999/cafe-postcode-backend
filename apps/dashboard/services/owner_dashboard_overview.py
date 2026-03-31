from django.db.models import Count, IntegerField, Sum, Value
from django.db.models.functions import Coalesce

from apps.orders.models import Order, OrderItem, Payment
from common.utils.date import tashkent_day_bounds, tashkent_now


class OwnerDashboardOverviewService:
    def get_today_range(self):
        return tashkent_day_bounds()

    def build(self, *, restaurant):
        start, end = self.get_today_range()

        succeeded_payments = Payment.objects.filter(
            order__restaurant=restaurant,
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=start,
            paid_at__lt=end,
        )
        sales_total = succeeded_payments.aggregate(
            total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField())
        )['total']

        closed_orders = Order.objects.filter(
            restaurant=restaurant,
            status=Order.Status.CLOSED,
            closed_at__gte=start,
            closed_at__lt=end,
        )
        orders_count = closed_orders.count()
        average_check = sales_total // orders_count if orders_count else 0

        top_items = list(
            OrderItem.objects.filter(
                order__restaurant=restaurant,
                order__status=Order.Status.CLOSED,
                order__closed_at__gte=start,
                order__closed_at__lt=end,
            )
            .exclude(status=OrderItem.Status.CANCELLED)
            .values('catalog_item__name')
            .annotate(
                quantity=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
                revenue=Coalesce(Sum('line_total'), Value(0), output_field=IntegerField()),
            )
            .order_by('-revenue', '-quantity', 'catalog_item__name')[:5]
        )

        waiter_breakdown = list(
            closed_orders.values('opened_by__id', 'opened_by__full_name')
            .annotate(
                orders_count=Count('id'),
                sales_total=Coalesce(Sum('total'), Value(0), output_field=IntegerField()),
            )
            .order_by('-sales_total', '-orders_count', 'opened_by__full_name')[:5]
        )

        cashier_breakdown = list(
            succeeded_payments.values('received_by__id', 'received_by__full_name')
            .annotate(
                orders_count=Count('order_id', distinct=True),
                sales_total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()),
            )
            .order_by('-sales_total', '-orders_count', 'received_by__full_name')[:5]
        )

        return {
            'generated_at': tashkent_now(),
            'restaurant': {
                'id': restaurant.id,
                'name': restaurant.name,
                'currency': restaurant.currency,
            },
            'sales_total': sales_total,
            'orders_count': orders_count,
            'average_check': average_check,
            'top_items': [
                {
                    'item_name': row['catalog_item__name'],
                    'quantity': row['quantity'],
                    'revenue': row['revenue'],
                }
                for row in top_items
            ],
            'waiter_breakdown': [
                {
                    'user_id': row['opened_by__id'],
                    'user_name': row['opened_by__full_name'],
                    'orders_count': row['orders_count'],
                    'sales_total': row['sales_total'],
                }
                for row in waiter_breakdown
            ],
            'cashier_breakdown': [
                {
                    'user_id': row['received_by__id'],
                    'user_name': row['received_by__full_name'],
                    'orders_count': row['orders_count'],
                    'sales_total': row['sales_total'],
                }
                for row in cashier_breakdown
            ],
        }
