from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_cash_expense_model
from apps.billing.serializers import (
    CashExpenseCreateSerializer,
    CashExpenseSerializer,
    CashExpenseVoidSerializer,
    ExpenseCategorySerializer,
)
from apps.billing.services import CashExpenseService
from apps.billing.services.edge_shift_recovery import materialize_edge_shift
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

CashExpense = get_cash_expense_model()


def _expense_queryset(restaurant):
    return CashExpense.objects.filter(restaurant=restaurant).select_related(
        'cash_shift',
        'cash_desk',
        'category',
        'recipient',
        'created_by',
        'voided_by',
    )


class PosExpenseCategoryListView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = CashExpenseService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        rows = self.service_class().get_active_categories(restaurant=restaurant)
        return Response(ExpenseCategorySerializer(rows, many=True).data)


class PosCashExpenseListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = CashExpenseService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        shift = self.service_class().resolve_active_shift(
            restaurant=restaurant,
            user=request.user,
            cash_shift_id=request.query_params.get('cash_shift_id') or request.query_params.get('cashShiftId'),
        )
        rows = _expense_queryset(restaurant).filter(cash_shift=shift).order_by('-occurred_at')
        return Response(CashExpenseSerializer(rows, many=True).data)

    def post(self, request):
        restaurant = get_request_restaurant(request)
        payload = request.data.copy()
        header_operation_id = str(request.headers.get('X-Edge-Operation-ID') or '').strip()
        body_operation_id = str(payload.get('edgeOperationId') or payload.get('edge_operation_id') or '').strip()
        if header_operation_id and body_operation_id and header_operation_id != body_operation_id:
            return Response({'edgeOperationId': ['Header va body operation ID mos emas.']}, status=400)
        if header_operation_id:
            payload['edge_operation_id'] = header_operation_id
        serializer = CashExpenseCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        trusted = bool(getattr(request._request, 'trusted_edge_replay', False))
        occurred_at = getattr(request._request, 'trusted_edge_occurred_at', None)
        shift_id = payload.get('edge_cash_shift_id') or serializer.validated_data.get('cash_shift_id')
        shift = materialize_edge_shift(restaurant=restaurant, shift_id=shift_id, body=payload, user=request.user,
                                       occurred_at=occurred_at) if trusted and shift_id else None
        expense = self.service_class().create_expense(
            restaurant=restaurant,
            user=request.user,
            trusted_edge_replay=trusted, cash_shift=shift, occurred_at=occurred_at,
            **serializer.validated_data,
        )
        return Response(CashExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)


class PosCashExpenseVoidView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = CashExpenseService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        expense = _expense_queryset(restaurant).filter(pk=pk).first()
        if expense is None:
            return Response({'detail': 'Xarajat topilmadi.'}, status=404)
        serializer = CashExpenseVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense = self.service_class().void_expense(
            expense=expense,
            user=request.user,
            reason=serializer.validated_data['reason'],
            trusted_edge_replay=bool(getattr(request._request, 'trusted_edge_replay', False)),
            occurred_at=getattr(request._request, 'trusted_edge_occurred_at', None),
            edge_operation_id=str(request.headers.get('X-Edge-Operation-ID') or ''),
        )
        return Response(CashExpenseSerializer(expense).data)


__all__ = ['PosCashExpenseListCreateView', 'PosCashExpenseVoidView', 'PosExpenseCategoryListView']
