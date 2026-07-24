from rest_framework import status

from apps.billing.models import Payment
from apps.catalog.models import CatalogItem
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.printing.models import PrintDocument
from apps.restaurants.models import PrepStation
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import Permission


class BackendKitchenScenarioTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.bar_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name="Bar",
            kind=PrepStation.Kind.BAR,
        )
        self.bar_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name="Choy",
            prep_station=self.bar_station,
            price=5000,
        )

    def test_submit_groups_stations_aggregates_items_and_reuses_unchanged_documents(self):
        self._bind_kitchen_printer()
        order = self._open_order()
        self._add_item(order, self.catalog_item)
        self._add_item(order, self.catalog_item)
        self._add_item(order, self.bar_item)

        submitted = self._submit(order)

        tickets = {
            ticket.prep_station_id: ticket
            for ticket in KitchenTicket.objects.filter(order=order).select_related("print_document")
        }
        kitchen_ticket = tickets[self.prep_station.id]
        bar_ticket = tickets[self.bar_station.id]
        self.assertEqual(kitchen_ticket.routed_via, KitchenTicket.RouteMode.BOTH)
        self.assertEqual(bar_ticket.routed_via, KitchenTicket.RouteMode.DISPLAY)
        self.assertEqual(submitted["kitchenPrintDocuments"], [str(kitchen_ticket.print_document_id)])
        self.assertIsNotNone(bar_ticket.print_document_id)
        self.assertEqual(
            kitchen_ticket.print_document.data_snapshot["items"],
            [
                {
                    "name": "Osh",
                    "quantity": 2,
                    "unitPrice": 30000,
                    "lineTotal": 60000,
                    "note": "",
                    "modifierText": "",
                    "modifiers": [],
                }
            ],
        )
        first_document_ids = {
            self.prep_station.id: kitchen_ticket.print_document_id,
            self.bar_station.id: bar_ticket.print_document_id,
        }

        replayed_submit = self._submit(order)

        refreshed = {
            ticket.prep_station_id: ticket
            for ticket in KitchenTicket.objects.filter(order=order)
        }
        self.assertEqual(
            {station_id: ticket.print_document_id for station_id, ticket in refreshed.items()},
            first_document_ids,
        )
        self.assertEqual(replayed_submit["kitchenPrintDocuments"], [str(first_document_ids[self.prep_station.id])])
        self.assertEqual(PrintDocument.objects.filter(source_model="kitchen.kitchenticket").count(), 2)

    def test_submitted_item_add_returns_only_the_changed_printer_revision(self):
        self._bind_kitchen_printer()
        order = self._open_order()
        self._add_item(order, self.catalog_item)
        self._add_item(order, self.bar_item)
        self._submit(order)
        tickets = {
            ticket.prep_station_id: ticket
            for ticket in KitchenTicket.objects.filter(order=order)
        }
        original_kitchen_document = tickets[self.prep_station.id].print_document_id
        original_bar_document = tickets[self.bar_station.id].print_document_id

        response = self.client.post(
            f"/api/v1/pos/sales/orders/{order.id}/items/",
            {"catalogItem": str(self.catalog_item.id), "quantity": 2, "note": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        tickets = {
            ticket.prep_station_id: ticket
            for ticket in KitchenTicket.objects.filter(order=order).select_related("print_document")
        }
        kitchen_ticket = tickets[self.prep_station.id]
        self.assertNotEqual(kitchen_ticket.print_document_id, original_kitchen_document)
        self.assertEqual(kitchen_ticket.print_document.metadata["revision"], 2)
        self.assertEqual(tickets[self.bar_station.id].print_document_id, original_bar_document)
        self.assertEqual(response.data["kitchenPrintDocuments"], [str(kitchen_ticket.print_document_id)])
        self.assertEqual(kitchen_ticket.print_document.data_snapshot["items"][0]["quantity"], 3)

    def test_ticket_statuses_drive_item_states_and_order_ready_without_new_document_content(self):
        self._bind_kitchen_printer()
        order = self._open_order()
        self._add_item(order, self.catalog_item)
        self._add_item(order, self.bar_item)
        self._submit(order)
        tickets = {
            ticket.prep_station_id: ticket
            for ticket in KitchenTicket.objects.filter(order=order)
        }
        original_documents = {station_id: ticket.print_document_id for station_id, ticket in tickets.items()}

        cooking = self._update_ticket(tickets[self.prep_station.id], KitchenTicket.Status.COOKING)
        done_kitchen = self._update_ticket(tickets[self.prep_station.id], KitchenTicket.Status.DONE)

        order.refresh_from_db()
        self.assertEqual(cooking["status"], KitchenTicket.Status.COOKING)
        self.assertEqual(done_kitchen["status"], KitchenTicket.Status.DONE)
        self.assertEqual(order.status, Order.Status.SUBMITTED)
        self.assertFalse(
            order.items.filter(prep_station=self.prep_station).exclude(status=OrderItem.Status.DONE).exists()
        )

        self._update_ticket(tickets[self.bar_station.id], KitchenTicket.Status.DONE)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.READY)
        self.assertFalse(order.items.exclude(status=OrderItem.Status.DONE).exists())
        self.assertEqual(
            {
                ticket.prep_station_id: ticket.print_document_id
                for ticket in KitchenTicket.objects.filter(order=order)
            },
            original_documents,
        )

    def test_payment_submits_an_open_order_but_does_not_return_an_existing_kitchen_document(self):
        self._allow_plain_payment()
        self._bind_kitchen_printer()
        self.create_cash_shift()
        open_order = self._open_order()
        self._add_item(open_order, self.catalog_item)

        first_payment = self._pay_plain(open_order)

        first_ticket = KitchenTicket.objects.get(order=open_order, prep_station=self.prep_station)
        self.assertEqual(first_payment["kitchenPrintDocuments"], [str(first_ticket.print_document_id)])

        submitted_order = self._open_order()
        self._add_item(submitted_order, self.catalog_item)
        self._submit(submitted_order)
        existing_document_id = KitchenTicket.objects.get(
            order=submitted_order,
            prep_station=self.prep_station,
        ).print_document_id

        second_payment = self._pay_plain(submitted_order)

        self.assertEqual(second_payment["kitchenPrintDocuments"], [])
        self.assertEqual(
            KitchenTicket.objects.get(order=submitted_order, prep_station=self.prep_station).print_document_id,
            existing_document_id,
        )

    def _open_order(self):
        payload = self.create_order_via_api(
            {
                "distributionPoint": str(self.takeaway_distribution.id),
                "channel": Order.Channel.TAKEAWAY,
                "guestCount": 1,
            }
        )
        return Order.objects.get(pk=payload["id"])

    def _add_item(self, order, item):
        return self.add_item_via_api(order.id, catalog_item=item)

    def _submit(self, order):
        return self.submit_order_via_api(order.id)

    def _update_ticket(self, ticket, ticket_status):
        response = self.client.post(
            f"/api/v1/pos/kitchen/tickets/{ticket.id}/status/",
            {"status": ticket_status},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def _bind_kitchen_printer(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider="windows-raw",
            settings={"connection_type": "system_printer", "printer_name": "Kitchen Printer"},
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=["printer_integration", "updated_at"])

    def _allow_plain_payment(self):
        permission, _ = Permission.objects.get_or_create(
            code="pos_fiscal_receipts.skip",
            defaults={"name": "Skip fiscal receipt", "description": "Skip fiscal receipt"},
        )
        self.role.permissions.add(permission)
        self.entitlement.permissions.add(permission)

    def _pay_plain(self, order):
        order.refresh_from_db()
        response = self.client.post(
            f"/api/v1/pos/billing/orders/{order.id}/pay/",
            {
                "method": Payment.Method.CASH,
                "amount": order.total,
                "registerFiscal": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data
