from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.catalog.models import ModifierGroup, ModifierOption
from apps.kitchen.models import KitchenTicket, KitchenTicketLine
from apps.sales.models import Order, OrderItem, OrderItemMarking, OrderItemModifier
from apps.sales.selectors.orders import pos_order_queryset
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase


class PosOrderQuerysetTests(PosTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.modifier_group = ModifierGroup.objects.create(
            restaurant=cls.restaurant,
            name="Qo'shimchalar",
            selection_type=ModifierGroup.SelectionType.SINGLE,
            max_selections=1,
        )
        cls.modifier_option = ModifierOption.objects.create(
            group=cls.modifier_group,
            name="Achchiq sous",
            price_delta=2000,
        )

    def create_order_graph(self, sequence: int) -> Order:
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=sequence,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            subtotal=32000,
            total=32000,
        )
        order_item = OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            base_unit_price=30000,
            unit_price=32000,
        )
        OrderItemModifier.objects.create(
            order_item=order_item,
            modifier_option=self.modifier_option,
            group_name=self.modifier_group.name,
            option_name=self.modifier_option.name,
            price_delta=2000,
        )
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=self.catalog_item,
            raw_code=f"marking-{sequence}",
            gtin=f"{sequence:014d}",
            serial=str(sequence),
            scanned_by=self.user,
        )
        ticket = KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=order,
            prep_station=self.prep_station,
            dispatch_number=sequence,
        )
        KitchenTicketLine.objects.create(ticket=ticket, order_item=order_item)
        payment = Payment.objects.create(
            order=order,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=32000,
            status=Payment.Status.SUCCEEDED,
        )
        PaymentRefund.objects.create(
            payment=payment,
            amount=1000,
            reason="Test refund",
            refunded_by=self.user,
            status=PaymentRefund.Status.SUCCEEDED,
        )
        Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            provider="mock",
        )
        return order

    def test_serializer_relation_graph_has_constant_query_count(self):
        first_order = self.create_order_graph(101)
        second_order = self.create_order_graph(102)

        queryset = pos_order_queryset(
            Order.objects.filter(pk__in=[first_order.pk, second_order.pk])
        ).order_by("order_number")

        with self.assertNumQueries(7):
            data = OrderSerializer(queryset, many=True).data

        self.assertEqual([order["order_number"] for order in data], [101, 102])

    def test_serializer_output_keeps_nested_order_data(self):
        order = self.create_order_graph(103)

        with self.assertNumQueries(7):
            data = OrderSerializer(
                pos_order_queryset(Order.objects.filter(pk=order.pk)).get()
            ).data

        item = data["items"][0]
        modifier = item["modifiers"][0]
        refund = data["payments"][0]["refunds"][0]
        self.assertEqual(item["catalog_item_name"], self.catalog_item.name)
        self.assertEqual(item["prep_station_name"], self.prep_station.name)
        self.assertEqual(item["kitchen_dispatch_number"], 103)
        self.assertEqual(item["markings"][0]["rawCode"], "marking-103")
        self.assertEqual(modifier["option_id"], str(self.modifier_option.id))
        self.assertEqual(modifier["group_id"], str(self.modifier_group.id))
        self.assertEqual(refund["refunded_by_name"], self.user.full_name)
        self.assertEqual(len(data["receipts"]), 1)
