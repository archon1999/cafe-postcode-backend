from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from asgiref.sync import sync_to_async
from django.db import connection, connections, transaction
from django.db.models import F
from django.test import TransactionTestCase
from django.utils import timezone

from apps.local_agents.models import (
    LocalAgent,
    LocalAgentCommand,
    LocalAgentMutationInbox,
    LocalAgentMutationAttempt,
)
from apps.local_agents.mutation_inbox import receive_and_apply
from apps.local_agents.services import LocalAgentCommandService, LocalAgentCommandError
from apps.restaurants.models import Restaurant


class FinancialInboxTransactionTests(TransactionTestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="Durable inbox test")
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.operation = {
            "operationId": "pos:" + str(uuid.uuid4()),
            "userId": str(uuid.uuid4()),
            "method": "POST",
            "path": "/api/v1/pos/billing/shifts/current/close/",
            "body": {"edgeCashShiftId": str(uuid.uuid4())},
            "occurredAt": timezone.now().isoformat(),
        }

    def apply(self, operation):
        Restaurant.objects.filter(pk=self.restaurant.pk).update(
            last_order_number=F("last_order_number") + 1
        )
        return {
            "operationId": operation["operationId"],
            "ok": True,
            "status": 200,
            "body": {"closed": True},
        }

    def test_concurrent_replay_applies_business_once_and_both_ack(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks and independent connections.")
        barrier = Barrier(2)

        def run():
            try:
                barrier.wait(timeout=10)
                agent = LocalAgent.objects.select_related("restaurant").get(
                    pk=self.agent.pk
                )
                return receive_and_apply(
                    agent=agent, operation=self.operation, apply=self.apply
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, 1)
        self.assertTrue(all(result["applied"] for result in results))
        self.assertEqual(LocalAgentMutationInbox.objects.count(), 1)
        self.assertEqual(LocalAgentMutationAttempt.objects.count(), 1)

    def test_failure_rolls_back_projection_but_preserves_received_evidence(self):
        def crash(operation):
            self.apply(operation)
            raise RuntimeError("crash after business write before acknowledgment")

        result = receive_and_apply(
            agent=self.agent, operation=self.operation, apply=crash
        )
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, 0)
        self.assertTrue(result["durablyReceived"])
        self.assertFalse(result["applied"])
        self.assertEqual(
            LocalAgentMutationInbox.objects.get().operation, self.operation
        )
        retried = receive_and_apply(
            agent=self.agent, operation=self.operation, apply=self.apply
        )
        self.assertTrue(retried["applied"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, 1)
        self.assertEqual(LocalAgentMutationAttempt.objects.count(), 2)

    def test_changed_payload_does_not_overwrite_original_or_apply(self):
        first = receive_and_apply(
            agent=self.agent, operation=self.operation, apply=self.apply
        )
        changed = {**self.operation, "body": {"amount": 777}}
        second = receive_and_apply(
            agent=self.agent, operation=changed, apply=self.apply
        )
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(second["inboxState"], "conflict")
        self.assertEqual(
            LocalAgentMutationInbox.objects.get().operation, self.operation
        )
        self.assertTrue(
            LocalAgentMutationAttempt.objects.filter(operation=changed).exists()
        )

    def test_transport_attempt_counter_is_not_immutable_identity(self):
        first = receive_and_apply(
            agent=self.agent,
            operation={**self.operation, "attempts": 0},
            apply=self.apply,
        )
        retry = receive_and_apply(
            agent=self.agent,
            operation={**self.operation, "attempts": 1},
            apply=self.apply,
        )
        self.assertTrue(retry["applied"])
        self.assertEqual(first["payloadHash"], retry["payloadHash"])
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, 1)

    def test_dependency_receipt_is_not_applied_until_parent(self):
        parent = {**self.operation, "operationId": "parent:" + str(uuid.uuid4())}
        dependent = {**self.operation, "dependsOn": [parent["operationId"]]}
        first = receive_and_apply(
            agent=self.agent, operation=dependent, apply=self.apply
        )
        self.assertTrue(first["durablyReceived"])
        self.assertFalse(first["applied"])
        self.assertEqual(first["missingDependencies"], [parent["operationId"]])
        receive_and_apply(agent=self.agent, operation=parent, apply=self.apply)
        self.assertTrue(
            receive_and_apply(agent=self.agent, operation=dependent, apply=self.apply)[
                "applied"
            ]
        )

    def test_sequence_conflict_preserves_competing_envelope(self):
        first = {
            **self.operation,
            "eventVersion": 2,
            "ownerEpoch": "owner-a",
            "sequence": 1,
        }
        receive_and_apply(agent=self.agent, operation=first, apply=self.apply)
        competing = {**first, "operationId": "other:" + str(uuid.uuid4())}
        result = receive_and_apply(
            agent=self.agent, operation=competing, apply=self.apply
        )
        self.assertEqual(result["code"], "EVENT_SEQUENCE_CONFLICT")
        self.assertTrue(
            LocalAgentMutationAttempt.objects.filter(operation=competing).exists()
        )

    def test_sync_rpc_inside_transaction_refused_before_command_or_dispatch(self):
        with (
            transaction.atomic(),
            self.assertRaises(LocalAgentCommandError) as captured,
        ):
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type="local_http.request",
                payload={},
            )
        self.assertEqual(captured.exception.code, "AGENT_RPC_IN_TRANSACTION")
        self.assertFalse(LocalAgentCommand.objects.exists())

    def test_offline_owner_keeps_committed_financial_intent(self):
        from apps.local_agents.services import LocalAgentUnavailableError
        payload = {'operationId': self.operation['operationId'], 'userId': self.operation['userId'],
                   'method': 'POST', 'path': '/pos/billing/shifts/current/close/', 'body': {}}
        with self.assertRaises(LocalAgentUnavailableError):
            LocalAgentCommandService().execute(restaurant=self.restaurant, command_type='financial.execute', payload=payload)
        command = LocalAgentCommand.objects.get()
        self.assertEqual(command.financial_operation_id, self.operation['operationId'])
        self.assertEqual(command.payload, payload)
        self.assertIsNone(command.sent_at)

    def test_committed_remote_command_visible_to_separate_consumer_and_reused(self):
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save()
        seen = []

        def store_result(command_id):
            seen.append(
                LocalAgentCommand.objects.get(pk=command_id).financial_operation_id
            )
            LocalAgentCommand.objects.filter(pk=command_id).update(
                status="succeeded",
                result={"responseStatus": 200, "response": {"ok": True}},
            )

        async def group_send(group, event):
            await sync_to_async(store_result, thread_sensitive=False)(
                event["command_id"]
            )

        payload = {
            "operationId": self.operation["operationId"],
            "userId": self.operation["userId"],
            "path": "/pos/billing/shifts/current/close/",
            "method": "POST",
            "body": {},
        }
        with patch(
            "apps.local_agents.services.get_channel_layer",
            return_value=SimpleNamespace(group_send=group_send),
        ):
            result = LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type="financial.execute",
                payload=payload,
            )
            again = LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type="financial.execute",
                payload=payload,
            )
        self.assertEqual(result, again)
        self.assertEqual(seen, [self.operation["operationId"]])
        self.assertEqual(LocalAgentCommand.objects.count(), 1)
