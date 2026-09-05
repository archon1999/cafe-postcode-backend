import json

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.serializers import (
    CashierContextSerializer,
    CashShiftCloseSerializer,
    CashShiftOpenSerializer,
    CashShiftReportSerializer,
    FiscalShiftSerializer,
)
from apps.billing.services import CashShiftService
from apps.billing.services.financial_authority import dispatch_to_financial_owner
from apps.billing.services.edge_shift_recovery import materialize_edge_shift
from apps.billing.services.receipt_context import parse_payload_datetime
from apps.platform.services import FeatureGateService
from apps.restaurants.helpers import get_cash_desk_model
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

from .open_checks import OpenCheckListView

CashDesk = get_cash_desk_model()
User = get_user_model()


class FiscalShiftEndpointRBACPermission(EndpointRBACPermission):
    """Allow an agent to report an already-completed local fiscal side effect.

    Interactive fiscal-shift commands still require the registered
    ``pos_fiscal_shift.manage`` permission.  A trusted Local Agent replay is a
    lifecycle acknowledgement, however, and commonly belongs to the cashier
    who was allowed to create the fiscal payment in the first place.
    """

    edge_result_fields = {
        "edge_fiscal_result",
        "edge_fiscal_result_json",
        "edgeFiscalResult",
        "edgeFiscalResultJson",
    }

    def has_permission(self, request, view):
        raw_request = getattr(request, "_request", request)
        if bool(getattr(raw_request, "trusted_edge_replay", False)) and any(
            field in request.data for field in self.edge_result_fields
        ):
            return bool(request.user and request.user.is_authenticated)
        return super().has_permission(request, view)


class CashierContextView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        payload = self.shift_service_class().build_context(
            restaurant=restaurant, user=request.user
        )
        return Response(CashierContextSerializer(payload).data)


class CashShiftOpenView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        if not bool(getattr(request._request, 'trusted_edge_replay', False)):
            return dispatch_to_financial_owner(request=request, restaurant=restaurant)
        serializer = CashShiftOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        edge_cash_shift_id = serializer.validated_data.get("edge_cash_shift_id")
        trusted_edge_replay = bool(
            getattr(request._request, "trusted_edge_replay", False)
        )
        if edge_cash_shift_id is not None and not trusted_edge_replay:
            raise ValidationError(
                {"edgeCashShiftId": "Only a trusted local agent may bind a shift ID."}
            )

        available_cash_desks = self.shift_service_class().get_available_cash_desks(
            restaurant=restaurant
        )
        cash_desk_id = serializer.validated_data.get("cash_desk_id")
        if cash_desk_id is None:
            if len(available_cash_desks) != 1:
                return Response(
                    {"cashDeskId": ["Cash desk selection is required."]}, status=400
                )
            cash_desk = available_cash_desks[0]
        else:
            cash_desk = CashDesk.objects.filter(
                restaurant=restaurant, pk=cash_desk_id, is_active=True
            ).first()
            if cash_desk is None:
                return Response(
                    {"cashDeskId": ["Selected cash desk was not found."]}, status=400
                )

        cashier = None
        cashier_id = serializer.validated_data.get("cashier_id") or (request.data.get('edge_cashier_id') if trusted_edge_replay else None)
        if cashier_id is not None:
            cashier = (
                User.objects.filter(
                    pk=cashier_id,
                    restaurant_profile__restaurant=restaurant,
                    is_active=True,
                )
                .select_related("role", "restaurant_profile", "employee_profile")
                .first()
            )
            if cashier is None:
                return Response(
                    {"cashierId": ["Selected cashier was not found."]}, status=400
                )
        elif trusted_edge_replay:
            # The owner defaults omitted assignment to the acting cashier.
            # Preserve that resolved fact even for a custom cashier role.
            cashier = request.user
        elif len(available_cash_desks) > 1:
            return Response(
                {"cashierId": ["Cashier selection is required."]}, status=400
            )

        self.shift_service_class().open_shift(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=request.user,
            cashier=cashier,
            opening_cash_amount=serializer.validated_data.get("opening_cash_amount", 0),
            notes_open=serializer.validated_data.get("notes_open", ""),
            shift_id=edge_cash_shift_id,
            opened_at=(parse_payload_datetime(request.data.get('edge_cash_shift_opened_at')) or getattr(request._request, 'trusted_edge_occurred_at', None)) if trusted_edge_replay else None,
            closed_at=parse_payload_datetime(request.data.get('edge_cash_shift_closed_at')) if trusted_edge_replay else None,
            trusted_edge_replay=trusted_edge_replay,
        )
        payload = self.shift_service_class().build_context(
            restaurant=restaurant, user=request.user
        )
        return Response(CashierContextSerializer(payload).data, status=201)


class CashShiftCloseView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        if not bool(getattr(request._request, 'trusted_edge_replay', False)):
            return dispatch_to_financial_owner(request=request, restaurant=restaurant)
        with transaction.atomic():
            return self._apply_close(request, restaurant)

    def _apply_close(self, request, restaurant):
        serializer = CashShiftCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_shift_id = serializer.validated_data.get("cash_shift_id") or request.data.get('edge_cash_shift_id')
        if cash_shift_id:
            shift = materialize_edge_shift(restaurant=restaurant, shift_id=cash_shift_id,
                body=request.data, user=request.user,
                occurred_at=getattr(request._request, 'trusted_edge_occurred_at', None), closing=True)
        else:
            shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        if shift is None:
            return Response({"detail": "There is no active cashier shift."}, status=400)

        # Serialize projection of this exact close with historical payment facts.
        # Physical actions have already completed in the owner journal.
        shift = (
            type(shift).objects.select_for_update(of=("self",))
            .select_related("cash_desk", "cashier", "opened_by")
            .get(pk=shift.pk)
        )

        shift_service = self.shift_service_class()
        fiscal_shift_payload = None
        print_report_error = ""
        # Fiscal close is its own already-performed evidence event, enqueued
        # before this close by the owner. Never perform a second physical close.
        fiscal_result = FiscalShiftOpenView()._edge_provider_result(request=request, cash_desk=shift.cash_desk)
        if fiscal_result is not None:
            fiscal_shift_payload = shift_service.close_fiscal_shift(
                restaurant=restaurant, cash_desk=shift.cash_desk, closed_by=request.user,
                provider_result=fiscal_result,
                occurred_at=getattr(request._request, 'trusted_edge_occurred_at', None),
                session_key=str((getattr(request._request, 'trusted_edge_envelope', {}) or {}).get('fiscalSessionId') or ''))
        else:
            fiscal_session = shift_service._get_active_fiscal_session(restaurant=restaurant, cash_desk=shift.cash_desk)
            event_time = parse_payload_datetime(request.data.get('edge_cash_shift_closed_at')) or getattr(request._request, 'trusted_edge_occurred_at', None)
            if fiscal_session is not None and (event_time is None or fiscal_session.opened_at <= event_time):
                raise ValidationError({'code': 'FISCAL_CLOSE_DEPENDENCY_PENDING', 'detail': 'Apply the original fiscal-close evidence before finalizing this cash shift.'})
        expected_snapshot = request.data.get('edge_close_snapshot')
        envelope = getattr(request._request, 'trusted_edge_envelope', {}) or {}
        if envelope.get('eventVersion') == 2 and not isinstance(expected_snapshot, dict):
            raise ValidationError({'code': 'SHIFT_SNAPSHOT_REQUIRED', 'detail': 'A v2 close requires immutable owner totals.'})
        if isinstance(expected_snapshot, dict):
            snapshot = shift_service.build_shift_snapshot(shift=shift)
            try:
                mismatches = {key: {'owner': value, 'backend': snapshot[key]}
                    for key, value in expected_snapshot.items() if key in snapshot and int(value or 0) != int(snapshot[key] or 0)}
            except (TypeError, ValueError) as error:
                raise ValidationError({'code': 'SHIFT_SNAPSHOT_INVALID', 'detail': 'Close totals must contain integer monetary values.'}) from error
            if mismatches:
                raise ValidationError({'code': 'SHIFT_TOTALS_CONFLICT', 'detail': 'Close totals differ from applied financial events.', 'differences': mismatches})
        shift = shift_service.close_shift(
            shift=shift,
            actual_closing_cash_amount=serializer.validated_data.get(
                "actual_closing_cash_amount"
            ),
            closed_by=request.user,
            notes_close=serializer.validated_data.get("notes_close", ""),
            trusted_edge_replay=True,
            closed_at=parse_payload_datetime(request.data.get('edge_cash_shift_closed_at')) or getattr(request._request, 'trusted_edge_occurred_at', None),
            close_sequence=(getattr(request._request, 'trusted_edge_envelope', {}) or {}).get('sequence'),
        )

        payload = shift_service.build_context(restaurant=restaurant, user=request.user)
        try:
            print_documents = shift_service.create_shift_report_documents(
                shift=shift,
                created_by=request.user,
                closed=True,
            )
        except Exception as error:
            print_documents = []
            print_report_error = str(error)
        response_payload = {
            **CashierContextSerializer(payload).data,
            "report": shift_service.build_fiscal_shift_report(shift=shift),
            "printDocuments": [str(document.id) for document in print_documents],
        }
        if print_report_error:
            response_payload["printReportError"] = print_report_error
        if fiscal_shift_payload is not None:
            response_payload["fiscal_shift"] = fiscal_shift_payload
        return Response(response_payload)


class CashShiftReportPrintView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        serializer = CashShiftReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shifts = self.shift_service_class().get_active_shifts_for_manager(
            restaurant=restaurant, user=request.user
        )
        shift_id = serializer.validated_data.get("cash_shift_id")
        if shift_id is not None:
            shift = next((item for item in shifts if item.id == shift_id), None)
        else:
            shift = shifts[0] if len(shifts) == 1 else None
        if shift is None:
            return Response({"detail": "Faol smena topilmadi."}, status=400)
        documents = self.shift_service_class().print_shift_reports(
            shift=shift, created_by=request.user
        )
        return Response(
            {"printDocuments": [str(document.id) for document in documents]}
        )


class FiscalShiftOpenView(APIView):
    permission_classes = [permissions.IsAuthenticated, FiscalShiftEndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        if not bool(getattr(request._request, 'trusted_edge_replay', False)):
            return dispatch_to_financial_owner(request=request, restaurant=restaurant)
        serializer = FiscalShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cash_desk = self._resolve_cash_desk(
            restaurant=restaurant,
            cash_desk_id=serializer.validated_data.get("cash_desk_id"),
        )
        provider_result = self._edge_provider_result(
            request=request, cash_desk=cash_desk
        )
        result = self.shift_service_class().open_fiscal_shift(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=request.user,
            provider_result=provider_result,
            occurred_at=getattr(request._request, 'trusted_edge_occurred_at', None),
            session_key=str((getattr(request._request, 'trusted_edge_envelope', {}) or {}).get('fiscalSessionId') or ''),
        )
        return Response(result, status=201)

    def _edge_provider_result(self, *, request, cash_desk):
        result = request.data.get("edge_fiscal_result")
        result_json = request.data.get("edge_fiscal_result_json")
        if result is None and result_json is None:
            return None
        if not bool(getattr(request._request, "trusted_edge_replay", False)):
            raise ValidationError(
                {
                    "edgeFiscalResult": "Only a trusted local agent may submit fiscal results."
                }
            )
        if result_json is not None:
            if result is not None:
                raise ValidationError(
                    {"edgeFiscalResult": "Submit fiscal result in only one format."}
                )
            try:
                result = json.loads(result_json)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    {"edgeFiscalResult": "Fiscal result JSON is invalid."}
                ) from error
        return self.shift_service_class().validate_edge_fiscal_shift_result(
            result=result, cash_desk=cash_desk
        )

    def _resolve_cash_desk(self, *, restaurant, cash_desk_id):
        if cash_desk_id is None:
            available = self.shift_service_class().get_available_cash_desks(
                restaurant=restaurant
            )
            if len(available) == 1:
                return available[0]
            return None
        cash_desk = CashDesk.objects.filter(
            restaurant=restaurant, pk=cash_desk_id, is_active=True
        ).first()
        if cash_desk is None:
            raise ValidationError({"cashDeskId": "Selected cash desk was not found."})
        return cash_desk


class FiscalShiftCloseView(FiscalShiftOpenView):
    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        if not bool(getattr(request._request, 'trusted_edge_replay', False)):
            return dispatch_to_financial_owner(request=request, restaurant=restaurant)
        serializer = FiscalShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cash_desk = self._resolve_cash_desk(
            restaurant=restaurant,
            cash_desk_id=serializer.validated_data.get("cash_desk_id"),
        )
        provider_result = self._edge_provider_result(
            request=request, cash_desk=cash_desk
        )
        try:
            payload = self.shift_service_class().close_fiscal_shift(
                restaurant=restaurant,
                cash_desk=cash_desk,
                closed_by=request.user,
                provider_result=provider_result,
            occurred_at=getattr(request._request, 'trusted_edge_occurred_at', None),
            session_key=str((getattr(request._request, 'trusted_edge_envelope', {}) or {}).get('fiscalSessionId') or ''),
            )
        except Exception as error:
            detail = str(error)
            if "9032" in detail or "CANNOT_CLOSE_EMPTY_ZREPORT" in detail:
                detail = "Fiscal smenani yopib bo‘lmaydi: fiscal smenada savdo yoki qaytim operatsiyasi yo‘q."
            raise ValidationError({"detail": detail}) from error
        return Response(payload)


__all__ = [
    "CashierContextView",
    "CashShiftCloseView",
    "CashShiftOpenView",
    "FiscalShiftCloseView",
    "FiscalShiftOpenView",
    "OpenCheckListView",
]
