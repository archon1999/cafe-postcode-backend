from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.serializers import CashShiftCloseSerializer, CashShiftOpenSerializer, CashierContextSerializer
from apps.billing.services import CashShiftService
from apps.platform.services import FeatureGateService
from apps.restaurants.helpers import get_cash_desk_model
from apps.sales.helpers import get_order_model
from apps.sales.serializers import OrderSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.utils.date import tashkent_day_bounds

CashDesk = get_cash_desk_model()
Order = get_order_model()


class CashierContextView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        payload = self.shift_service_class().build_context(restaurant=restaurant, user=request.user)
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

        available_cash_desks = self.shift_service_class().get_available_cash_desks(restaurant=restaurant)
        cash_desk_id = serializer.validated_data.get('cash_desk_id')
        if cash_desk_id is None:
            if len(available_cash_desks) != 1:
                return Response({'cashDeskId': ['Cash desk selection is required.']}, status=400)
            cash_desk = available_cash_desks[0]
        else:
            cash_desk = CashDesk.objects.filter(restaurant=restaurant, pk=cash_desk_id, is_active=True).first()
            if cash_desk is None:
                return Response({'cashDeskId': ['Selected cash desk was not found.']}, status=400)

        self.shift_service_class().open_shift(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=request.user,
            opening_cash_amount=serializer.validated_data.get('opening_cash_amount', 0),
            notes_open=serializer.validated_data.get('notes_open', ''),
        )
        payload = self.shift_service_class().build_context(restaurant=restaurant, user=request.user)
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

        shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        if shift is None:
            return Response({'detail': 'There is no active cashier shift.'}, status=400)

        self.shift_service_class().close_shift(
            shift=shift,
            actual_closing_cash_amount=serializer.validated_data['actual_closing_cash_amount'],
            closed_by=request.user,
            notes_close=serializer.validated_data.get('notes_close', ''),
        )
        payload = self.shift_service_class().build_context(restaurant=restaurant, user=request.user)
        return Response(CashierContextSerializer(payload).data)


class OpenCheckListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        status_filter = self.request.query_params.get('status', 'open')
        queryset = (
            Order.objects.filter(restaurant=restaurant)
            .select_related(
                'table_session',
                'table_session__hall',
                'table_session__table',
                'opened_by',
                'cashier',
            )
            .prefetch_related('items__catalog_item', 'items__prep_station', 'payments', 'receipts')
        )
        if status_filter == 'closed':
            start, end = tashkent_day_bounds()
            return queryset.filter(status=Order.Status.CLOSED, closed_at__gte=start, closed_at__lt=end)

        return queryset.filter(status__in=[Order.Status.SUBMITTED, Order.Status.READY])

__all__ = ['CashierContextView', 'CashShiftCloseView', 'CashShiftOpenView', 'OpenCheckListView']
