from django.test import SimpleTestCase

from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.local_agents.mutation_reconciliation import allowed_mutation
from apps.local_agents.mutation_results import mutation_result_metadata


class LocalAgentMutationLifecycleTests(SimpleTestCase):
    def test_local_agent_operational_paths_are_allowed(self):
        self.assertTrue(
            allowed_mutation("POST", "/api/v1/pos/billing/shifts/current/print-report/")
        )
        self.assertTrue(
            allowed_mutation("POST", "/api/v1/pos/billing/shifts/current/expenses/")
        )
        self.assertTrue(
            allowed_mutation(
                "POST",
                "/api/v1/pos/billing/expenses/00000000-0000-4000-8000-000000000001/void/",
            )
        )

    def test_contract_failures_are_quarantined_with_machine_readable_code(self):
        result = LocalAgentMutationProcessor().process(
            agent=None,
            operation={
                "operationId": "contract-failure",
                "userId": "user",
                "method": "POST",
                "path": "/api/v1/pos/not-allowed/",
                "body": {},
            },
        )

        self.assertEqual(result["classification"], "quarantined")
        self.assertEqual(result["code"], "MUTATION_PATH_NOT_ALLOWED")
        self.assertTrue(result["resolutionHint"])
        self.assertFalse(result["retryable"])

    def test_response_metadata_separates_retry_action_and_superseded(self):
        self.assertEqual(
            mutation_result_metadata(response_status=503)["classification"],
            "retry",
        )
        self.assertEqual(
            mutation_result_metadata(response_status=400)["classification"],
            "action_required",
        )
        self.assertEqual(
            mutation_result_metadata(response_status=200, reconciled=True)[
                "classification"
            ],
            "superseded",
        )
