import uuid

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.sales.tests.support.pos_api import PosAPITestCase


class FinancialCommandStatusTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)

    def command(self, body, status=409, user_id=None):
        operation_id = "pos:" + str(uuid.uuid4())
        LocalAgentCommand.objects.create(
            agent=self.agent,
            command_type="financial.execute",
            financial_operation_id=operation_id,
            status="succeeded",
            payload={"userId": str(user_id or self.user.pk)},
            result={"responseStatus": status, "response": body},
        )
        return operation_id

    def test_rpc_success_with_owner_unknown_remains_unknown(self):
        operation = self.command(
            {"financialCommand": {"state": "unknown"}, "code": "TIMEOUT"}
        )
        response = self.client.get(f"/api/v1/pos/financial-commands/{operation}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "unknown")
        self.assertFalse(response.json()["retryAllowed"])

    def test_unclassified_error_is_never_definitive_failure(self):
        operation = self.command({"code": "CONNECTION_LOST"})
        response = self.client.get(f"/api/v1/pos/financial-commands/{operation}/")
        self.assertEqual(response.json()["state"], "unknown")

    def test_only_owner_explicit_failure_is_failed(self):
        operation = self.command(
            {"financialCommand": {"state": "failed"}, "detail": "definitive rejection"}
        )
        response = self.client.get(f"/api/v1/pos/financial-commands/{operation}/")
        self.assertEqual(response.json()["state"], "failed")

    def test_command_lookup_is_scoped_to_original_user(self):
        operation = self.command({"order": "private"}, status=200, user_id=uuid.uuid4())
        response = self.client.get(f"/api/v1/pos/financial-commands/{operation}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private", str(response.content))

    def test_old_agent_cannot_receive_new_financial_command(self):
        response = self.client.post(
            "/api/v1/pos/billing/shifts/open/",
            {"cashDeskId": str(self.cash_desk.pk)},
            format="json",
            HTTP_X_EDGE_OPERATION_ID="pos:" + str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "FINANCIAL_OWNER_UPGRADE_REQUIRED")
        self.assertFalse(LocalAgentCommand.objects.exists())
