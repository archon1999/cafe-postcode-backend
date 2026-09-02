import json
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.urls import Resolver404, resolve
from djangorestframework_camel_case.util import camelize
from rest_framework import status
from rest_framework.test import force_authenticate

from apps.billing.models import CashShift
from apps.billing.serializers import CashierContextSerializer
from apps.billing.services import CashShiftService
from apps.kitchen.models import KitchenTicket
from apps.local_agents.models import LocalAgentMutationReceipt
from apps.local_agents.mutation_reconciliation import (
    decode_response,
    reconciled_fully_paid_order,
    reconciled_order_item_delete,
    reconciled_terminal_noop,
)
from apps.local_agents.mutation_results import (
    CLASSIFICATION_QUARANTINED,
    mutation_error_result,
    mutation_result_metadata,
)


class LocalAgentMutationDispatchMixin:
    @staticmethod
    def _prepare_dispatch(*, agent, operation_id, path, body):
        dispatch_path = path
        if path == "/api/v1/pos/billing/shifts/current/close/":
            edge_cash_shift_id = body.pop(
                "edgeCashShiftId", body.pop("edge_cash_shift_id", None)
            )
            edge_cashier_id = body.pop(
                "edgeCashierId", body.pop("edge_cashier_id", None)
            )
            edge_cash_desk_id = body.pop(
                "edgeCashDeskId", body.pop("edge_cash_desk_id", None)
            )
            if edge_cash_shift_id:
                shift = CashShift.objects.filter(
                    pk=edge_cash_shift_id,
                    cash_desk__restaurant=agent.restaurant,
                    status=CashShift.Status.OPEN,
                ).first()
                if shift is None:
                    return dispatch_path, mutation_error_result(
                        operation_id=operation_id,
                        response_status=409,
                        error="Originating cashier shift is not synchronized or is no longer open.",
                        retryable=False,
                        code="EDGE_CASH_SHIFT_NOT_OPEN",
                    )
                body["cashShiftId"] = str(shift.id)
            elif edge_cashier_id and edge_cash_desk_id:
                shift = (
                    CashShift.objects.filter(
                        cash_desk__restaurant=agent.restaurant,
                        cash_desk_id=edge_cash_desk_id,
                        status=CashShift.Status.OPEN,
                    )
                    .filter(
                        Q(cashier_id=edge_cashier_id) | Q(opened_by_id=edge_cashier_id)
                    )
                    .order_by("opened_at")
                    .first()
                )
                if shift is None:
                    return dispatch_path, mutation_error_result(
                        operation_id=operation_id,
                        response_status=409,
                        error="Cashier shift is not synchronized yet.",
                        retryable=True,
                        code="CASH_SHIFT_NOT_SYNCHRONIZED",
                    )
                body["cashShiftId"] = str(shift.id)
        if re.fullmatch(r"/api/v1/pos/kitchen/tickets/[0-9a-f-]+/status/", path):
            edge_order_id = body.pop("edgeOrderId", body.pop("edge_order_id", None))
            prep_station_id = body.pop(
                "prepStationId", body.pop("prep_station_id", None)
            )
            if edge_order_id and prep_station_id:
                ticket = KitchenTicket.objects.filter(
                    restaurant=agent.restaurant,
                    order_id=edge_order_id,
                    prep_station_id=prep_station_id,
                ).first()
                if ticket is None:
                    return dispatch_path, mutation_error_result(
                        operation_id=operation_id,
                        response_status=409,
                        error="Kitchen ticket is not synchronized yet.",
                        retryable=True,
                        code="KITCHEN_TICKET_NOT_SYNCHRONIZED",
                    )
                dispatch_path = f"/api/v1/pos/kitchen/tickets/{ticket.id}/status/"
        return dispatch_path, None

    def _dispatch(
        self, *, agent, user, operation_id, method, path, dispatch_path, body, digest, occurred_at
    ):
        try:
            match = resolve(dispatch_path)
        except Resolver404:
            return mutation_error_result(
                operation_id=operation_id,
                response_status=404,
                error="Mutation endpoint was not found.",
                code="MUTATION_ENDPOINT_NOT_FOUND",
                classification=CLASSIFICATION_QUARANTINED,
            )

        factory = self.request_factory_class()
        internal_request = factory.generic(
            method,
            dispatch_path,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
            HTTP_X_EDGE_OPERATION_ID=operation_id,
        )
        internal_request.trusted_edge_replay = True
        internal_request.trusted_edge_occurred_at = occurred_at
        internal_request.resolver_match = match
        force_authenticate(internal_request, user=user)
        response = match.func(internal_request, *match.args, **match.kwargs)
        response_body = decode_response(response)
        response_status = int(response.status_code)
        reconciled_delete = reconciled_order_item_delete(
            method=method,
            path=path,
            response_status=response_status,
            response_body=response_body,
        )
        if reconciled_delete is not None:
            response_status = status.HTTP_204_NO_CONTENT
            response_body = reconciled_delete
        reconciled_payment = reconciled_fully_paid_order(
            agent=agent,
            method=method,
            path=path,
            response_status=response_status,
            response_body=response_body,
        )
        if reconciled_payment is not None:
            response_status = status.HTTP_200_OK
            response_body = reconciled_payment
        reconciled_noop = reconciled_terminal_noop(
            agent=agent,
            method=method,
            path=path,
            response_status=response_status,
            response_body=response_body,
        )
        if reconciled_noop is not None:
            response_status = status.HTTP_200_OK
            response_body = reconciled_noop

        if response_status < 500:
            LocalAgentMutationReceipt.objects.create(
                restaurant=agent.restaurant,
                operation_id=operation_id,
                user_id=user.id,
                method=method,
                path=path,
                request_hash=digest,
                response_status=response_status,
                response_body=response_body if response_body is not None else {},
            )
        result = {
            "operationId": operation_id,
            "ok": 200 <= response_status < 300,
            "status": response_status,
            "body": response_body,
            "replayed": False,
            "reconciled": reconciled_delete is not None
            or reconciled_payment is not None
            or reconciled_noop is not None,
            "retryable": response_status >= 500,
        }
        result.update(
            mutation_result_metadata(
                response_status=response_status,
                response_body=response_body,
                retryable=response_status >= 500,
                reconciled=result["reconciled"],
            )
        )
        return result

    @staticmethod
    def _reconcile_open_shift(*, agent, user, operation_id, method, path, digest, body):
        edge_cash_shift_id = body.get("edgeCashShiftId") or body.get(
            "edge_cash_shift_id"
        )
        cash_desk_id = body.get("cashDeskId") or body.get("cash_desk_id")
        requested_cashier_id = str(
            body.get("cashierId") or body.get("cashier_id") or user.id
        )
        shifts = CashShift.objects.filter(
            cash_desk__restaurant=agent.restaurant,
            status=CashShift.Status.OPEN,
        ).select_related("cash_desk", "cashier", "opened_by")
        if cash_desk_id:
            shifts = shifts.filter(cash_desk_id=cash_desk_id)
        if edge_cash_shift_id:
            shifts = shifts.filter(pk=edge_cash_shift_id)

        matching = [
            shift
            for shift in shifts
            if str(shift.cashier_id or shift.opened_by_id) == requested_cashier_id
        ]
        if len(matching) != 1:
            return None

        response_body = camelize(
            json.loads(
                json.dumps(
                    CashierContextSerializer(
                        CashShiftService().build_context(
                            restaurant=agent.restaurant, user=user
                        )
                    ).data,
                    cls=DjangoJSONEncoder,
                )
            )
        )
        response_status = status.HTTP_200_OK
        LocalAgentMutationReceipt.objects.create(
            restaurant=agent.restaurant,
            operation_id=operation_id,
            user_id=user.id,
            method=method,
            path=path,
            request_hash=digest,
            response_status=response_status,
            response_body=response_body,
        )
        result = {
            "operationId": operation_id,
            "ok": True,
            "status": response_status,
            "body": response_body,
            "replayed": False,
            "reconciled": True,
            "retryable": False,
        }
        result.update(
            mutation_result_metadata(
                response_status=response_status,
                response_body=response_body,
                reconciled=True,
            )
        )
        return result
