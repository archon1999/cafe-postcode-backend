import json

from django.contrib.auth import get_user_model
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
from apps.platform.services import FeatureGateService
from apps.restaurants.helpers import get_cash_desk_model
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

from .open_checks import OpenCheckListView

CashDesk = get_cash_desk_model()
User = get_user_model()


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
        serializer = CashShiftOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

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
        cashier_id = serializer.validated_data.get("cashier_id")
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
        serializer = CashShiftCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cash_shift_id = serializer.validated_data.get("cash_shift_id")
        if cash_shift_id is not None:
            shift = self.shift_service_class().get_active_shifts_for_manager(
                restaurant=restaurant, user=request.user
            )
            shift = next((item for item in shift if item.id == cash_shift_id), None)
        else:
            shift = self.shift_service_class().get_active_shift(
                restaurant=restaurant, user=request.user
            )
        if shift is None:
            return Response({"detail": "There is no active cashier shift."}, status=400)

        shift_service = self.shift_service_class()
        fiscal_shift_payload = None
        print_report_error = ""
        fiscal_shift_open = shift_service.has_open_fiscal_shift(restaurant=restaurant)
        if serializer.validated_data.get("close_fiscal_shift") and fiscal_shift_open:
            active_manager_shifts = shift_service.get_active_shifts_for_manager(
                restaurant=restaurant, user=request.user
            )
            has_other_open_shifts = any(
                item.pk != shift.pk for item in active_manager_shifts
            )
            if has_other_open_shifts:
                raise ValidationError(
                    {
                        "closeFiscalShift": "Fiscal smena faqat oxirgi kassa smenasi yopilgandan keyin yopiladi."
                    }
                )
            try:
                fiscal_shift_payload = shift_service.close_fiscal_shift(
                    restaurant=restaurant, closed_by=request.user
                )
            except ValidationError:
                raise
            except Exception as error:
                detail = str(error)
                if "9032" in detail or "CANNOT_CLOSE_EMPTY_ZREPORT" in detail:
                    detail = "Fiscal smenani yopib bo'lmaydi: fiscal smenada savdo yoki qaytim operatsiyasi yo'q."
                raise ValidationError({"detail": detail}) from error

        fiscal_report = None
        if fiscal_shift_payload is not None:
            provider_report = fiscal_shift_payload.get("provider_report") or {}
            fiscal_report = dict(provider_report.get("z_info") or {})
            result = fiscal_shift_payload.get("result") or {}
            fiscal_report.setdefault(
                "FactoryID", result.get("factory_id") or result.get("factoryId") or ""
            )
            fiscal_report.setdefault(
                "TerminalID",
                result.get("terminal_id") or result.get("terminalId") or "",
            )
        elif fiscal_shift_open:
            try:
                fiscal_report = shift_service.get_open_fiscal_report(shift=shift)
            except Exception as error:
                print_report_error = str(error)

        shift_service.close_shift(
            shift=shift,
            actual_closing_cash_amount=serializer.validated_data.get(
                "actual_closing_cash_amount"
            ),
            closed_by=request.user,
            notes_close=serializer.validated_data.get("notes_close", ""),
        )

        payload = shift_service.build_context(restaurant=restaurant, user=request.user)
        try:
            print_documents = shift_service.create_shift_report_documents(
                shift=shift,
                created_by=request.user,
                closed=True,
                fiscal_report=fiscal_report,
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
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
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
