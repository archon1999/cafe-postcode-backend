from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicketLine
from apps.printing.models import PrintDocument
from apps.printing.services import create_kitchen_cancellation_print_document
from apps.sales.models import Order, OrderItem, OrderItemMarking, OrderItemModifier
from apps.sales.services import OrderSubmissionService
from apps.sales.services.marking import OrderMarkingScanService
from apps.sales.tests.support.pos_api import PosAPITestCase


class OrderMarkingScanServiceTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.service = OrderMarkingScanService()
        self.marked_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Marked cola',
            prep_station=self.prep_station,
            price=12000,
            requires_marking=True,
            marking_gtin='04780012960214',
        )
        self.raw_code = '01047800129602142174jZF/l!h&hBm93lKpu'
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=1001,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )

    def _enable_kitchen_printer(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'Kitchen Printer',
            },
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=['printer_integration', 'updated_at'])
        return printer

    def test_scan_add_creates_order_item_with_marking(self):
        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        order_item = OrderItem.objects.get(order=self.order, catalog_item=self.marked_item)
        marking = OrderItemMarking.objects.get(order_item=order_item)
        self.assertEqual(order_item.quantity, 1)
        self.assertEqual(order_item.created_by_id, self.user.id)
        self.assertEqual(order_item.base_unit_price, 12000)
        self.assertEqual(order_item.unit_price, 12000)
        self.assertEqual(marking.raw_code, self.raw_code)
        self.assertEqual(marking.gtin, '04780012960214')
        self.order.refresh_from_db()
        self.assertEqual(self.order.subtotal, 12000)

    def test_scan_matches_tasnif_international_code_without_leading_zero(self):
        self.marked_item.marking_gtin = ''
        self.marked_item.mxik_payload = {'label': 1, 'internationalCode': '4780012960214'}
        self.marked_item.save(update_fields=['marking_gtin', 'mxik_payload', 'updated_at'])

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        order_item = OrderItem.objects.get(order=self.order, catalog_item=self.marked_item)
        marking = OrderItemMarking.objects.get(order_item=order_item)
        self.assertEqual(marking.gtin, '04780012960214')
        self.assertEqual(order_item.quantity, 1)

    def test_scan_add_attaches_to_existing_unmarked_item(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        self.order.recalculate_totals()

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        self.assertEqual(OrderItem.objects.filter(order=self.order, catalog_item=self.marked_item).count(), 1)
        order_item.refresh_from_db()
        self.assertEqual(order_item.quantity, 1)
        self.assertEqual(order_item.markings.count(), 1)
        self.assertEqual(order_item.markings.get().raw_code, self.raw_code)
        self.assertEqual(order_item.created_by_id, self.user.id)

    def test_scan_add_creates_new_item_when_existing_item_is_fully_marked(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=self.marked_item,
            raw_code='010478001296021421OTHER',
            gtin='04780012960214',
            serial='OTHER',
            scanned_by=self.user,
        )
        self.order.recalculate_totals()

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        self.assertEqual(OrderItem.objects.filter(order=self.order, catalog_item=self.marked_item).count(), 2)
        self.assertEqual(
            sum(
                item.quantity
                for item in OrderItem.objects.filter(order=self.order, catalog_item=self.marked_item)
            ),
            2,
        )

    def test_scan_remove_deletes_matching_order_item(self):
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        self.order.recalculate_totals()

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='remove')

        self.assertFalse(OrderItem.objects.filter(order=self.order, catalog_item=self.marked_item).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 0)

    def test_scan_remove_prints_one_unit_cancellation_for_dispatched_single_item(self):
        self._enable_kitchen_printer()
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        self.order.recalculate_totals()
        OrderSubmissionService().submit(self.order)
        original_line = KitchenTicketLine.objects.select_related('ticket__print_document').get(
            order_item=order_item,
        )
        original_document_id = original_line.ticket.print_document_id
        self.assertEqual(
            original_line.ticket.print_document.data_snapshot['items'][0]['quantity'],
            1,
        )
        self.service.scan(
            order=self.order,
            raw_code=self.raw_code,
            scanned_by=self.user,
            mode='attach',
        )
        self.assertTrue(order_item.markings.filter(raw_code=self.raw_code).exists())

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{self.order.id}/scan-marking/',
            {'rawCode': self.raw_code, 'mode': 'remove'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        order_item.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(order_item.status, OrderItem.Status.CANCELLED)
        self.assertTrue(
            KitchenTicketLine.objects.filter(order_item=order_item).exists()
        )
        self.assertFalse(order_item.markings.exists())
        self.assertEqual(self.order.total, 0)
        self.assertEqual(response.data['marking_status']['missing_count'], 0)
        self.assertEqual(response.data['kitchenDispatchCount'], 0)
        self.assertEqual(len(response.data['kitchenPrintDocuments']), 1)

        cancellation_document = PrintDocument.objects.get(
            pk=response.data['kitchenPrintDocuments'][0],
        )
        self.assertEqual(cancellation_document.operation_type, PrintDocument.OperationType.REFUND)
        self.assertEqual(cancellation_document.source_model, 'sales.orderitem')
        self.assertEqual(cancellation_document.source_id, order_item.id)
        self.assertEqual(cancellation_document.metadata['prepStationId'], str(self.prep_station.id))
        self.assertEqual(cancellation_document.metadata['quantityDelta'], -1)
        self.assertEqual(cancellation_document.data_snapshot['items'][0]['quantity'], -1)
        self.assertEqual(cancellation_document.data_snapshot['items'][0]['lineTotal'], -12000)
        self.assertTrue(
            cancellation_document.data_snapshot['items'][0]['name'].startswith('BEKOR QILISH: '),
        )
        self.assertEqual(
            cancellation_document.data_snapshot['kitchen']['operation'],
            'cancellation',
        )
        self.assertEqual(
            cancellation_document.data_snapshot['kitchen']['quantityDelta'],
            -1,
        )
        self.assertEqual(
            original_line.ticket.print_document.data_snapshot['items'][0]['quantity'],
            1,
        )
        self.assertEqual(original_line.ticket.print_document_id, original_document_id)

        self.marked_item.name = 'Renamed after cancellation'
        self.marked_item.save(update_fields=['name', 'updated_at'])
        repeated_document, _snapshot = create_kitchen_cancellation_print_document(
            ticket=original_line.ticket,
            order_item=order_item,
            quantity_delta=-1,
            created_by=self.user,
        )
        self.assertEqual(repeated_document.id, cancellation_document.id)
        self.assertEqual(
            PrintDocument.objects.filter(
                restaurant=self.restaurant,
                idempotency_key=f'kitchen-cancellation:{order_item.id}',
            ).count(),
            1,
        )

    def test_scan_remove_splits_dispatched_multi_quantity_item_and_dispatches_only_remainder(self):
        self._enable_kitchen_printer()
        second_raw_code = '010478001296021421SECOND'
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=None,
            quantity=2,
            base_unit_price=10000,
            unit_price=12000,
            note='No ice',
        )
        OrderItemModifier.objects.create(
            order_item=order_item,
            group_name='Size',
            option_name='Large',
            price_delta=2000,
            sort_order=7,
        )
        for raw_code, serial in (
            (self.raw_code, '74jZF/l!h&hBm93lKpu'),
            (second_raw_code, 'SECOND'),
        ):
            OrderItemMarking.objects.create(
                order_item=order_item,
                catalog_item=self.marked_item,
                raw_code=raw_code,
                gtin='04780012960214',
                serial=serial,
                scanned_by=self.user,
            )
        self.order.recalculate_totals()
        OrderSubmissionService().submit(self.order)
        original_line = KitchenTicketLine.objects.select_related('ticket__print_document').get(
            order_item=order_item,
        )
        original_document_id = original_line.ticket.print_document_id
        self.marked_item.price = 99000
        self.marked_item.save(update_fields=['price', 'updated_at'])

        pending_catalog_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Pending soup',
            prep_station=self.prep_station,
            price=5000,
        )
        pending_order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=pending_catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            base_unit_price=5000,
            unit_price=5000,
        )

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{self.order.id}/scan-marking/',
            {'rawCode': self.raw_code, 'mode': 'remove'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        order_item.refresh_from_db()
        replacement = OrderItem.objects.exclude(pk=order_item.pk).get(
            order=self.order,
            catalog_item=self.marked_item,
        )
        replacement_line = KitchenTicketLine.objects.select_related('ticket__print_document').get(
            order_item=replacement,
        )
        self.order.refresh_from_db()

        self.assertEqual(order_item.status, OrderItem.Status.CANCELLED)
        self.assertEqual(order_item.quantity, 2)
        self.assertTrue(KitchenTicketLine.objects.filter(pk=original_line.pk).exists())
        self.assertEqual(original_line.ticket.print_document.data_snapshot['items'][0]['quantity'], 2)
        self.assertEqual(replacement.quantity, 1)
        self.assertEqual(replacement.catalog_item_id, order_item.catalog_item_id)
        self.assertEqual(replacement.prep_station_id, order_item.prep_station_id)
        self.assertIsNone(replacement.created_by_id)
        self.assertEqual(replacement.base_unit_price, 10000)
        self.assertEqual(replacement.unit_price, 12000)
        self.assertEqual(replacement.line_total, 12000)
        self.assertEqual(replacement.note, 'No ice')
        self.assertEqual(
            list(replacement.markings.values_list('raw_code', flat=True)),
            [second_raw_code],
        )
        self.assertFalse(OrderItemMarking.objects.filter(raw_code=self.raw_code).exists())
        self.assertEqual(
            list(
                replacement.modifiers.values_list(
                    'group_name',
                    'option_name',
                    'price_delta',
                    'sort_order',
                )
            ),
            [('Size', 'Large', 2000, 7)],
        )
        self.assertEqual(replacement_line.ticket.dispatch_number, 2)
        self.assertIsNone(replacement_line.ticket.print_document_id)
        self.assertEqual(replacement_line.ticket.printed_payload['status'], 'correction_only')
        self.assertTrue(replacement_line.ticket.printed_payload['sale_print_suppressed'])
        self.assertFalse(
            PrintDocument.objects.filter(
                restaurant=self.restaurant,
                source_model='kitchen.kitchenticket',
                source_id=replacement_line.ticket_id,
            ).exists(),
        )
        self.assertFalse(KitchenTicketLine.objects.filter(order_item=pending_order_item).exists())
        self.assertEqual(response.data['marking_status']['missing_count'], 0)
        self.assertEqual(response.data['kitchenDispatchCount'], 1)
        self.assertEqual(len(response.data['kitchenPrintDocuments']), 1)
        cancellation_document = PrintDocument.objects.get(
            pk=response.data['kitchenPrintDocuments'][0],
        )
        self.assertEqual(cancellation_document.operation_type, PrintDocument.OperationType.REFUND)
        self.assertEqual(cancellation_document.source_id, order_item.id)
        self.assertEqual(cancellation_document.metadata['prepStationId'], str(self.prep_station.id))
        self.assertEqual(cancellation_document.metadata['quantityDelta'], -1)
        self.assertEqual(cancellation_document.data_snapshot['items'][0]['quantity'], -1)
        self.assertEqual(cancellation_document.data_snapshot['items'][0]['lineTotal'], -12000)
        self.assertTrue(
            cancellation_document.data_snapshot['items'][0]['name'].startswith('BEKOR QILISH: '),
        )
        self.assertEqual(cancellation_document.data_snapshot['kitchen']['operation'], 'cancellation')
        self.assertEqual(original_line.ticket.print_document_id, original_document_id)
        self.assertEqual(original_line.ticket.print_document.data_snapshot['items'][0]['quantity'], 2)
        self.assertEqual(self.order.subtotal, 17000)

        duplicate_response = self.client.post(
            f'/api/v1/pos/sales/orders/{self.order.id}/scan-marking/',
            {'rawCode': self.raw_code, 'mode': 'remove'},
            format='json',
        )

        self.assertEqual(duplicate_response.status_code, 400, duplicate_response.data)
        replacement.refresh_from_db()
        self.assertEqual(replacement.status, OrderItem.Status.NEW)
        self.assertEqual(replacement.quantity, 1)
        self.assertEqual(replacement.markings.count(), 1)
        self.assertEqual(KitchenTicketLine.objects.filter(order_item=replacement).count(), 1)
        self.assertEqual(
            PrintDocument.objects.filter(
                restaurant=self.restaurant,
                idempotency_key=f'kitchen-cancellation:{order_item.id}',
            ).count(),
            1,
        )

    def test_scan_remove_does_not_return_cancellation_document_for_display_only_station(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=self.marked_item,
            raw_code=self.raw_code,
            gtin='04780012960214',
            serial='74jZF/l!h&hBm93lKpu',
            scanned_by=self.user,
        )
        self.order.recalculate_totals()
        OrderSubmissionService().submit(self.order)
        original_line = KitchenTicketLine.objects.select_related('ticket').get(
            order_item=order_item,
        )
        self.assertEqual(original_line.ticket.routed_via, 'display')

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{self.order.id}/scan-marking/',
            {'rawCode': self.raw_code, 'mode': 'remove'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        order_item.refresh_from_db()
        self.assertEqual(order_item.status, OrderItem.Status.CANCELLED)
        self.assertEqual(response.data['kitchenDispatchCount'], 0)
        self.assertEqual(response.data['kitchenPrintDocuments'], [])
        self.assertFalse(
            PrintDocument.objects.filter(
                restaurant=self.restaurant,
                idempotency_key=f'kitchen-cancellation:{order_item.id}',
            ).exists(),
        )

    def test_scan_unknown_product_returns_validation_error(self):
        with self.assertRaises(ValidationError):
            self.service.scan(order=self.order, raw_code='019999999999999921ABC', scanned_by=self.user, mode='add')

    def test_submit_rejects_marked_item_without_marking(self):
        self.restaurant.marking_check_enabled = True
        self.restaurant.save(update_fields=['marking_check_enabled', 'updated_at'])
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )

        with self.assertRaises(ValidationError) as context:
            OrderSubmissionService().submit(self.order)

        self.assertEqual(int(context.exception.detail['details']['missingCount']), 1)

    def test_submit_skips_marking_validation_when_restaurant_setting_disabled(self):
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )

        OrderSubmissionService().submit(self.order)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SUBMITTED)

    def test_submit_rejects_partially_marked_quantity(self):
        self.restaurant.marking_check_enabled = True
        self.restaurant.save(update_fields=['marking_check_enabled', 'updated_at'])
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=2,
            unit_price=12000,
            line_total=24000,
        )
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=self.marked_item,
            raw_code=self.raw_code,
            gtin='04780012960214',
            serial='2174jZF/l!h&hBm93lKpu',
            scanned_by=self.user,
        )

        with self.assertRaises(ValidationError) as context:
            OrderSubmissionService().submit(self.order)

        self.assertEqual(int(context.exception.detail['details']['missingCount']), 1)

    def test_submit_accepts_marked_item_with_complete_markings(self):
        self.restaurant.marking_check_enabled = True
        self.restaurant.save(update_fields=['marking_check_enabled', 'updated_at'])
        order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=self.marked_item,
            raw_code=self.raw_code,
            gtin='04780012960214',
            serial='2174jZF/l!h&hBm93lKpu',
            scanned_by=self.user,
        )

        OrderSubmissionService().submit(self.order)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SUBMITTED)
