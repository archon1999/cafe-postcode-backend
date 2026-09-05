import json
import re

from rest_framework import status

from apps.billing.services.edge_shift_recovery import (
    can_recover_trusted_edge_payment,
)

from apps.local_agents.mutation_reconciliation import (
    reconciled_fully_paid_order,
    reconciled_order_item_delete,
    reconciled_terminal_noop,
)
from apps.local_agents.mutation_results import (
    CLASSIFICATION_QUARANTINED,
    mutation_error_result,
    mutation_result_metadata,
)


class LocalAgentMutationReplayMixin:
    @staticmethod
    def _replay_existing(
        *, agent, existing, operation_id, user_id, method, path, body, digest,
        occurred_at=None,
    ):
        if (
            existing.restaurant_id != agent.restaurant_id
            or existing.request_hash != digest
        ):
            return mutation_error_result(
                operation_id=operation_id,
                response_status=409,
                error="operationId already belongs to another mutation.",
                code="OPERATION_ID_CONFLICT",
                classification=CLASSIFICATION_QUARANTINED,
            )
        if not 200 <= existing.response_status < 300:
            # Received evidence/attempts are durable in the inbox. Re-evaluate
            # dependencies and validation; never delete the original evidence.
            return None
        result = {
            "operationId": operation_id,
            "ok": 200 <= existing.response_status < 300,
            "status": existing.response_status,
            "body": existing.response_body,
            "replayed": True,
            "retryable": False,
        }
        result.update(
            mutation_result_metadata(
                response_status=existing.response_status,
                response_body=existing.response_body,
            )
        )
        return result
