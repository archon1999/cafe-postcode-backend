import uuid
from datetime import timedelta, timezone as datetime_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIRequestFactory

from apps.billing.services import CashShiftService
from apps.local_agents.models import LocalAgentMutationReceipt
from apps.local_agents.mutation_dispatch import LocalAgentMutationDispatchMixin
from apps.local_agents.mutation_reconciliation import allowed_mutation, request_hash
from apps.local_agents.mutation_replay import LocalAgentMutationReplayMixin
from apps.local_agents.mutation_results import (
    CLASSIFICATION_ACTION_REQUIRED,
    CLASSIFICATION_QUARANTINED,
    mutation_error_result,
)
from apps.users.models import User
from apps.devices.models import Device


class LocalAgentMutationProcessor(
    LocalAgentMutationReplayMixin,
    LocalAgentMutationDispatchMixin,
):
    def __init__(self, request_factory_class=APIRequestFactory):
        self.request_factory_class = request_factory_class

    def process(self, *, agent, operation):
        if not isinstance(operation, dict):
            return mutation_error_result(
                response_status=400,
                error="Operation must be an object.",
                code="INVALID_MUTATION_OBJECT",
                classification=CLASSIFICATION_QUARANTINED,
            )

        operation_id = str(
            operation.get("operationId") or operation.get("operation_id") or ""
        ).strip()
        user_id = str(operation.get("userId") or operation.get("user_id") or "").strip()
        device_id = str(operation.get("deviceId") or operation.get("device_id") or "").strip()
        method = str(operation.get("method") or "").strip().upper()
        path = str(operation.get("path") or "").strip()
        body = operation.get("body") if isinstance(operation.get("body"), dict) else {}
        occurred_at, occurred_at_error = self._parse_occurred_at(
            operation.get("occurredAt") or operation.get("occurred_at")
        )
        if not operation_id or len(operation_id) > 128:
            return mutation_error_result(
                operation_id=operation_id,
                response_status=400,
                error="Invalid operationId.",
                code="INVALID_OPERATION_ID",
                classification=CLASSIFICATION_QUARANTINED,
            )
        if occurred_at_error:
            return mutation_error_result(
                operation_id=operation_id,
                response_status=400,
                error=occurred_at_error,
                code="INVALID_OPERATION_OCCURRED_AT",
                classification=CLASSIFICATION_QUARANTINED,
            )
        if not allowed_mutation(method, path):
            return mutation_error_result(
                operation_id=operation_id,
                response_status=403,
                error="Mutation path is not allowed.",
                code="MUTATION_PATH_NOT_ALLOWED",
                classification=CLASSIFICATION_QUARANTINED,
            )

        normalized_device_id = ''
        if device_id:
            try:
                normalized_device_id = str(uuid.UUID(device_id))
            except (ValueError, AttributeError, TypeError):
                normalized_device_id = ''
        if device_id and (
            not normalized_device_id
            or not Device.objects.filter(
                id=normalized_device_id,
                restaurant=agent.restaurant,
                type=Device.Type.POS_TERMINAL,
                status=Device.Status.ACTIVE,
                revoked_at__isnull=True,
            ).exists()
        ):
            return mutation_error_result(
                operation_id=operation_id,
                response_status=403,
                error="Originating POS device is revoked or outside this restaurant.",
                code="POS_DEVICE_INVALID",
                classification=CLASSIFICATION_QUARANTINED,
                resolution_hint="Review the revoked POS device and resolve this operation.",
            )

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
            return mutation_error_result(
                operation_id=operation_id,
                response_status=403,
                error="POS user is invalid.",
                code="POS_USER_INVALID",
                classification=CLASSIFICATION_ACTION_REQUIRED,
                resolution_hint=(
                    "Restore the POS user or resolve this operation as obsolete."
                ),
            )

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
            occurred_at=occurred_at,
        )

    @staticmethod
    def _parse_occurred_at(raw_value):
        if raw_value in (None, ""):
            return None, ""
        if not isinstance(raw_value, str):
            return None, "Operation occurredAt must be an ISO-8601 datetime."
        occurred_at = parse_datetime(raw_value.strip())
        if occurred_at is None or timezone.is_naive(occurred_at):
            return None, "Operation occurredAt must be an ISO-8601 datetime with timezone."
        occurred_at = occurred_at.astimezone(datetime_timezone.utc)
        if occurred_at > timezone.now() + timedelta(minutes=5):
            return None, "Operation occurredAt is too far in the future."
        return occurred_at, ""

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
