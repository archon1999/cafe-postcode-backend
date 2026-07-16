from typing import Any
from uuid import UUID

from apps.local_agents.models import LocalAgentMutationReceipt
from apps.restaurants.models import Restaurant


class MutationReceiptRepository:
    def find(self, *, operation_id: str) -> LocalAgentMutationReceipt | None:
        return LocalAgentMutationReceipt.objects.filter(operation_id=operation_id).first()

    def create(
        self,
        *,
        restaurant: Restaurant,
        operation_id: str,
        user_id: UUID,
        method: str,
        path: str,
        request_hash: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> LocalAgentMutationReceipt:
        return LocalAgentMutationReceipt.objects.create(
            restaurant=restaurant,
            operation_id=operation_id,
            user_id=user_id,
            method=method,
            path=path,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
        )

    def update_response(
        self,
        *,
        receipt: LocalAgentMutationReceipt,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        receipt.response_status = response_status
        receipt.response_body = response_body
        receipt.save(update_fields=['response_status', 'response_body', 'updated_at'])

    def delete(self, *, receipt: LocalAgentMutationReceipt) -> None:
        receipt.delete()
