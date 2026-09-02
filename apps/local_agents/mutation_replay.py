import json

from rest_framework import status

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
        *, agent, existing, operation_id, user_id, method, path, body, digest
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
        reconciled_delete = reconciled_order_item_delete(
            method=method,
            path=path,
            response_status=existing.response_status,
            response_body=existing.response_body,
        )
        if reconciled_delete is not None:
            existing.response_status = status.HTTP_204_NO_CONTENT
            existing.response_body = reconciled_delete
            existing.save(
                update_fields=["response_status", "response_body", "updated_at"]
            )
            result = {
                "operationId": operation_id,
                "ok": True,
                "status": status.HTTP_204_NO_CONTENT,
                "body": reconciled_delete,
                "replayed": True,
                "reconciled": True,
                "retryable": False,
            }
            result.update(
                mutation_result_metadata(
                    response_status=status.HTTP_204_NO_CONTENT,
                    response_body=reconciled_delete,
                    reconciled=True,
                )
            )
            return result
        reconciled_payment = reconciled_fully_paid_order(
            agent=agent,
            method=method,
            path=path,
            response_status=existing.response_status,
            response_body=existing.response_body,
        )
        if reconciled_payment is not None:
            existing.response_status = status.HTTP_200_OK
            existing.response_body = reconciled_payment
            existing.save(
                update_fields=["response_status", "response_body", "updated_at"]
            )
            result = {
                "operationId": operation_id,
                "ok": True,
                "status": status.HTTP_200_OK,
                "body": reconciled_payment,
                "replayed": True,
                "reconciled": True,
                "retryable": False,
            }
            result.update(
                mutation_result_metadata(
                    response_status=status.HTTP_200_OK,
                    response_body=reconciled_payment,
                    reconciled=True,
                )
            )
            return result
        reconciled_noop = reconciled_terminal_noop(
            agent=agent,
            method=method,
            path=path,
            response_status=existing.response_status,
            response_body=existing.response_body,
        )
        if reconciled_noop is not None:
            existing.response_status = status.HTTP_200_OK
            existing.response_body = reconciled_noop
            existing.save(
                update_fields=["response_status", "response_body", "updated_at"]
            )
            result = {
                "operationId": operation_id,
                "ok": True,
                "status": status.HTTP_200_OK,
                "body": reconciled_noop,
                "replayed": True,
                "reconciled": True,
                "retryable": False,
            }
            result.update(
                mutation_result_metadata(
                    response_status=status.HTTP_200_OK,
                    response_body=reconciled_noop,
                    reconciled=True,
                )
            )
            return result
        recoverable_shift_conflict = (
            path == "/api/v1/pos/billing/shifts/open/"
            and existing.response_status == status.HTTP_400_BAD_REQUEST
            and "already has an active shift"
            in json.dumps(existing.response_body).lower()
        )
        requested_cashier_id = str(
            body.get("cashierId") or body.get("cashier_id") or ""
        ).strip()
        recoverable_implicit_cashier = (
            path == "/api/v1/pos/billing/shifts/open/"
            and existing.response_status == status.HTTP_400_BAD_REQUEST
            and requested_cashier_id == user_id
            and "selected cashier was not found"
            in json.dumps(existing.response_body).lower()
        )
        if recoverable_shift_conflict or recoverable_implicit_cashier:
            existing.delete()
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
