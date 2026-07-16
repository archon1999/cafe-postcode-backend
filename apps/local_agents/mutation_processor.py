from rest_framework.test import APIRequestFactory

from apps.billing.services import CashShiftService
from apps.local_agents.models import LocalAgentMutationReceipt
from apps.local_agents.mutation_dispatch import LocalAgentMutationDispatchMixin
from apps.local_agents.mutation_reconciliation import allowed_mutation, request_hash
from apps.local_agents.mutation_replay import LocalAgentMutationReplayMixin
from apps.users.models import User


class LocalAgentMutationProcessor(
    LocalAgentMutationReplayMixin,
    LocalAgentMutationDispatchMixin,
):
    def __init__(self, request_factory_class=APIRequestFactory):
        self.request_factory_class = request_factory_class

    def process(self, *, agent, operation):
        if not isinstance(operation, dict):
            return {
                "ok": False,
                "status": 400,
                "error": "Operation must be an object.",
                "retryable": False,
            }

        operation_id = str(
            operation.get("operationId") or operation.get("operation_id") or ""
        ).strip()
        user_id = str(operation.get("userId") or operation.get("user_id") or "").strip()
        method = str(operation.get("method") or "").strip().upper()
        path = str(operation.get("path") or "").strip()
        body = operation.get("body") if isinstance(operation.get("body"), dict) else {}
        if not operation_id or len(operation_id) > 128:
            return {
                "operationId": operation_id,
                "ok": False,
                "status": 400,
                "error": "Invalid operationId.",
                "retryable": False,
            }
        if not allowed_mutation(method, path):
            return {
                "operationId": operation_id,
                "ok": False,
                "status": 403,
                "error": "Mutation path is not allowed.",
                "retryable": False,
            }

        digest = request_hash(user_id=user_id, method=method, path=path, body=body)
        existing = LocalAgentMutationReceipt.objects.filter(
            operation_id=operation_id
        ).first()
        if existing is not None:
            replay = self._replay_existing(
                agent=agent,
                existing=existing,
                operation_id=operation_id,
                user_id=user_id,
                method=method,
                path=path,
                body=body,
                digest=digest,
            )
            if replay is not None:
                return replay

        user = (
            User.objects.filter(
                id=user_id,
                restaurant_profile__restaurant=agent.restaurant,
                is_active=True,
            )
            .select_related("role", "restaurant_profile", "employee_profile")
            .first()
        )
        if user is None or not user.can_access_pos_ui:
            return {
                "operationId": operation_id,
                "ok": False,
                "status": 403,
                "error": "POS user is invalid.",
                "retryable": False,
            }

        if path == "/api/v1/pos/billing/shifts/open/":
            self._drop_implicit_invalid_cashier(body, user)
            reconciled = self._reconcile_open_shift(
                agent=agent,
                user=user,
                operation_id=operation_id,
                method=method,
                path=path,
                digest=digest,
                body=body,
            )
            if reconciled is not None:
                return reconciled

        dispatch_path, preparation_error = self._prepare_dispatch(
            agent=agent,
            operation_id=operation_id,
            path=path,
            body=body,
        )
        if preparation_error is not None:
            return preparation_error
        return self._dispatch(
            agent=agent,
            user=user,
            operation_id=operation_id,
            method=method,
            path=path,
            dispatch_path=dispatch_path,
            body=body,
            digest=digest,
        )

    @staticmethod
    def _drop_implicit_invalid_cashier(body, user):
        requested_cashier_id = str(
            body.get("cashierId") or body.get("cashier_id") or ""
        ).strip()
        role_code = getattr(user.role, "code", None)
        if (
            requested_cashier_id == str(user.id)
            and role_code not in CashShiftService.cashier_role_codes
        ):
            body.pop("cashierId", None)
            body.pop("cashier_id", None)
