from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.serializers.cashier_context import (
    CashShiftCloseSerializer,
    CashShiftOpenSerializer,
    CashierContextSerializer,
)
from apps.orders.services import CashShiftService
from apps.organizations.models import CashDesk
from apps.organizations.services import FeatureGateService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class CashierContextView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'cashshift.view'
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        branch = get_request_branch(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=branch.restaurant)
        payload = self.shift_service_class().build_context(branch=branch, user=request.user)
        return Response(CashierContextSerializer(payload).data)


class CashShiftOpenView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'cashshift.open'
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        branch = get_request_branch(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=branch.restaurant)
        serializer = CashShiftOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        available_cash_desks = self.shift_service_class().get_available_cash_desks(branch=branch)
        cash_desk_id = serializer.validated_data.get('cash_desk_id')
        if cash_desk_id is None:
            if len(available_cash_desks) != 1:
                return Response({'cashDeskId': ['Cash desk selection is required.']}, status=400)
            cash_desk = available_cash_desks[0]
        else:
            cash_desk = CashDesk.objects.filter(branch=branch, pk=cash_desk_id, is_active=True).first()
            if cash_desk is None:
                return Response({'cashDeskId': ['Selected cash desk was not found.']}, status=400)

        shift = self.shift_service_class().open_shift(
            branch=branch,
            cash_desk=cash_desk,
            opened_by=request.user,
            opening_cash_amount=serializer.validated_data.get('opening_cash_amount', 0),
            notes_open=serializer.validated_data.get('notes_open', ''),
        )
        payload = self.shift_service_class().build_context(branch=branch, user=request.user)
        return Response(CashierContextSerializer(payload).data, status=201)


class CashShiftCloseView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'cashshift.close'
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request):
        branch = get_request_branch(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=branch.restaurant)
        serializer = CashShiftCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shift = self.shift_service_class().get_active_shift(branch=branch, user=request.user)
        if shift is None:
            return Response({'detail': 'There is no active cashier shift.'}, status=400)

        self.shift_service_class().close_shift(
            shift=shift,
            actual_closing_cash_amount=serializer.validated_data['actual_closing_cash_amount'],
            closed_by=request.user,
            notes_close=serializer.validated_data.get('notes_close', ''),
        )
        payload = self.shift_service_class().build_context(branch=branch, user=request.user)
        return Response(CashierContextSerializer(payload).data)

