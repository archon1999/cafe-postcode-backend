import threading
import uuid

from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework import status

from apps.billing.models import CashShift
from apps.local_agents.models import LocalAgent, LocalAgentMutationReceipt
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.sales.services import OrderStateService
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User


class BackendNumberingScenarioTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        _agent, self.agent_token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name="Numbering characterization agent",
        )

    def test_sequential_numbers_restart_for_a_new_cash_shift(self):
        first_shift = self.create_cash_shift()

        first = self._create_counter_order()
        second = self._create_counter_order()

        first_shift.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertEqual(
            (first["order_number"], first["display_name"]),
            (1, "1"),
        )
        self.assertEqual(
            (second["order_number"], second["display_name"]),
            (2, "2"),
        )
        self.assertEqual(first_shift.next_order_number, 2)
        self.assertEqual(self.restaurant.last_order_number, 2)

        first_shift.status = CashShift.Status.CLOSED
        first_shift.closed_at = timezone.now()
        first_shift.save(update_fields=["status", "closed_at", "updated_at"])
        second_shift = self.create_cash_shift()

        third = self._create_counter_order()

        second_shift.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertEqual(
            (third["order_number"], third["display_name"]),
            (3, "1"),
        )
        self.assertEqual(second_shift.next_order_number, 1)
        self.assertEqual(self.restaurant.last_order_number, 3)

    def test_stale_edge_numbers_are_renumbered_and_operation_replay_is_idempotent(
        self,
    ):
        shift = self.create_cash_shift()
        order_ids = [uuid.uuid4(), uuid.uuid4()]
        operations = [
            self._edge_order_operation(
                operation_id=f"numbering-edge-{index}",
                order_id=order_id,
                requested_display_name=requested,
            )
            for index, (order_id, requested) in enumerate(
                zip(order_ids, ("5", "1"), strict=True),
                start=1,
            )
        ]

        first = self._push_operations(operations)
        replay = self._push_operations(operations)

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(
            [result["status"] for result in first.data["results"]],
            [status.HTTP_201_CREATED, status.HTTP_201_CREATED],
        )
        self.assertEqual(replay.status_code, status.HTTP_200_OK, replay.data)
        self.assertTrue(all(result["replayed"] for result in replay.data["results"]))
        orders = list(
            Order.objects.filter(id__in=order_ids)
            .order_by("created_at")
            .values_list("id", "display_name", "order_number")
        )
        self.assertEqual([row[0] for row in orders], order_ids)
        self.assertEqual([row[1] for row in orders], ["5", "6"])
        self.assertEqual([row[2] for row in orders], [1, 2])
        self.assertEqual(
            LocalAgentMutationReceipt.objects.filter(
                operation_id__in=[item["operationId"] for item in operations]
            ).count(),
            2,
        )
        shift.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertEqual(shift.next_order_number, 6)
        self.assertEqual(self.restaurant.last_order_number, 2)

        online = self._create_counter_order()

        shift.refresh_from_db()
        self.assertEqual(
            (online["order_number"], online["display_name"]),
            (3, "7"),
        )
        self.assertEqual(shift.next_order_number, 7)

    def _create_counter_order(self):
        response = self.client.post(
            "/api/v1/pos/sales/orders/",
            {
                "distributionPoint": str(self.takeaway_distribution.id),
                "channel": Order.Channel.TAKEAWAY,
                "guestCount": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def _edge_order_operation(
        self,
        *,
        operation_id: str,
        order_id: uuid.UUID,
        requested_display_name: str,
    ):
        return {
            "operationId": operation_id,
            "userId": str(self.user.id),
            "method": "POST",
            "path": "/api/v1/pos/sales/orders/",
            "body": {
                "id": str(order_id),
                "channel": Order.Channel.TAKEAWAY,
                "guestCount": 1,
                "displayName": requested_display_name,
            },
        }

    def _push_operations(self, operations):
        return self.client.post(
            "/api/v1/local-agent/sync/mutations/",
            {"operations": operations},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )


class BackendNumberingConcurrencyScenarioTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="Concurrent numbering")
        self.user = User.objects.create_user(
            username="concurrent-numbering-user",
            password="secret123",
            full_name="Concurrent Numbering User",
            restaurant=self.restaurant,
        )
        self.cash_desk = self.restaurant.cash_desks.create(name="Main")
        self.shift = CashShift.objects.create(
            cash_desk=self.cash_desk,
            opened_by=self.user,
            opened_at=timezone.now(),
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_allocations_are_serialized_by_the_cash_shift_row_lock(self):
        barrier = threading.Barrier(2)
        numbers = []
        failures = []
        result_lock = threading.Lock()

        def allocate():
            close_old_connections()
            try:
                restaurant = Restaurant.objects.get(pk=self.restaurant.pk)
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                with transaction.atomic():
                    value = OrderStateService().next_shift_display_name(
                        restaurant=restaurant,
                        user=user,
                    )
                with result_lock:
                    numbers.append(value)
            except Exception as exc:  # pragma: no cover - retained as thread evidence
                with result_lock:
                    failures.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=allocate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(failures, failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(numbers), ["1", "2"])
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.next_order_number, 2)
