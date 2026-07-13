from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from django.db.models import Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api.pos.serializers import OpenCheckOrderSerializer
from apps.billing.helpers import get_payment_model, get_payment_refund_model, get_receipt_model
from apps.billing.serializers import CashShiftCloseSerializer, CashShiftOpenSerializer, CashierContextSerializer, FiscalShiftSerializer
from apps.billing.services import CashShiftService
from apps.platform.services import FeatureGateService
from apps.restaurants.helpers import get_cash_desk_model
from apps.sales.helpers import get_order_item_model, get_order_model
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.utils.date import tashkent_day_bounds

CashDesk = get_cash_desk_model()
User = get_user_model()
Order = get_order_model()
OrderItem = get_order_item_model()
Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()

OPEN_CHECKS_DEFAULT_LIMIT = 100
OPEN_CHECKS_MAX_LIMIT = 500


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

        cashier = None
        cashier_id = serializer.validated_data.get('cashier_id')
        if cashier_id is not None:
            cashier = User.objects.filter(pk=cashier_id).select_related('role', 'restaurant_profile', 'employee_profile').first()
            if cashier is None:
                return Response({'cashierId': ['Selected cashier was not found.']}, status=400)
        elif len(available_cash_desks) > 1:
            return Response({'cashierId': ['Cashier selection is required.']}, status=400)

        self.shift_service_class().open_shift(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=request.user,
            cashier=cashier,
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

        cash_shift_id = serializer.validated_data.get('cash_shift_id')
        if cash_shift_id is not None:
            shift = self.shift_service_class().get_active_shifts_for_manager(restaurant=restaurant, user=request.user)
            shift = next((item for item in shift if item.id == cash_shift_id), None)
        else:
            shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        if shift is None:
            return Response({'detail': 'There is no active cashier shift.'}, status=400)

        shift_service = self.shift_service_class()
        fiscal_shift_payload = None
        if serializer.validated_data.get('close_fiscal_shift') and shift_service.has_open_fiscal_shift(restaurant=restaurant):
            active_manager_shifts = shift_service.get_active_shifts_for_manager(restaurant=restaurant, user=request.user)
            has_other_open_shifts = any(item.pk != shift.pk for item in active_manager_shifts)
            if has_other_open_shifts:
                raise ValidationError({'closeFiscalShift': 'Fiscal smena faqat oxirgi kassa smenasi yopilgandan keyin yopiladi.'})
            try:
                fiscal_shift_payload = shift_service.close_fiscal_shift(restaurant=restaurant, closed_by=request.user)
            except ValidationError:
                raise
            except Exception as error:
                detail = str(error)
                if '9032' in detail or 'CANNOT_CLOSE_EMPTY_ZREPORT' in detail:
                    detail = "Fiscal smenani yopib bo'lmaydi: fiscal smenada savdo yoki qaytim operatsiyasi yo'q."
                raise ValidationError({'detail': detail}) from error

        shift_service.close_shift(
            shift=shift,
            actual_closing_cash_amount=serializer.validated_data.get('actual_closing_cash_amount'),
            closed_by=request.user,
            notes_close=serializer.validated_data.get('notes_close', ''),
        )

        payload = shift_service.build_context(restaurant=restaurant, user=request.user)
        response_payload = {
            **CashierContextSerializer(payload).data,
            'report': shift_service.build_fiscal_shift_report(shift=shift),
        }
        if fiscal_shift_payload is not None:
            response_payload['fiscal_shift'] = fiscal_shift_payload
        return Response(
            response_payload
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
        cash_desk = self._resolve_cash_desk(restaurant=restaurant, cash_desk_id=serializer.validated_data.get('cash_desk_id'))
        result = self.shift_service_class().open_fiscal_shift(restaurant=restaurant, cash_desk=cash_desk, opened_by=request.user)
        return Response(result, status=201)

    def _resolve_cash_desk(self, *, restaurant, cash_desk_id):
        if cash_desk_id is None:
            available = self.shift_service_class().get_available_cash_desks(restaurant=restaurant)
            if len(available) == 1:
                return available[0]
            return None
        cash_desk = CashDesk.objects.filter(restaurant=restaurant, pk=cash_desk_id, is_active=True).first()
        if cash_desk is None:
            raise ValidationError({'cashDeskId': 'Selected cash desk was not found.'})
        return cash_desk


class FiscalShiftCloseView(FiscalShiftOpenView):
    def post(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        serializer = FiscalShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cash_desk = self._resolve_cash_desk(restaurant=restaurant, cash_desk_id=serializer.validated_data.get('cash_desk_id'))
        try:
            payload = self.shift_service_class().close_fiscal_shift(
                restaurant=restaurant,
                cash_desk=cash_desk,
                closed_by=request.user,
            )
        except Exception as error:
            detail = str(error)
            if '9032' in detail or 'CANNOT_CLOSE_EMPTY_ZREPORT' in detail:
                detail = 'Fiscal smenani yopib bo‘lmaydi: fiscal smenada savdo yoki qaytim operatsiyasi yo‘q.'
            raise ValidationError({'detail': detail}) from error
        return Response(payload)


class OpenCheckListView(generics.ListAPIView):
    serializer_class = OpenCheckOrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None
    feature_gate_service_class = FeatureGateService

    def get_status_filter(self):
        return self.request.query_params.get('status', 'open')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['include_billing'] = self.get_status_filter() in {'closed', 'fiscal_closed', 'fiscal_unresolved'}
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        if self.get_status_filter() in {'closed', 'fiscal_closed', 'fiscal_unresolved'}:
            page_size = self.get_page_size()
            paginator = Paginator(queryset, page_size)
            page_number = max(1, int(request.query_params.get('page') or 1))
            page = paginator.get_page(page_number)
            serializer = self.get_serializer(page.object_list, many=True)
            return Response(
                {
                    'data': serializer.data,
                    'count': paginator.count,
                    'page': page.number,
                    'page_size': page_size,
                    'num_pages': paginator.num_pages,
                }
            )
        return super().list(request, *args, **kwargs)

    def get_page_size(self):
        raw_page_size = self.request.query_params.get('page_size') or self.request.query_params.get('pageSize') or 25
        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError) as exc:
            raise ValidationError({'page_size': 'Page size must be a positive integer.'}) from exc
        return min(max(page_size, 1), 100)

    def get_limit(self):
        raw_limit = self.request.query_params.get('limit')
        if raw_limit is None:
            return OPEN_CHECKS_DEFAULT_LIMIT
        if raw_limit == 'all':
            return None
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValidationError({'limit': 'Limit must be a positive integer or "all".'}) from exc
        if limit < 1:
            raise ValidationError({'limit': 'Limit must be a positive integer or "all".'})
        return min(limit, OPEN_CHECKS_MAX_LIMIT)

    def apply_limit(self, queryset):
        limit = self.get_limit()
        if limit is None:
            return queryset
        return queryset[:limit]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        status_filter = self.get_status_filter()
        item_queryset = OrderItem.objects.select_related('catalog_item', 'prep_station').only(
            'id',
            'order_id',
            'catalog_item_id',
            'catalog_item__name',
            'prep_station_id',
            'prep_station__name',
            'quantity',
            'unit_price',
            'line_total',
            'status',
            'note',
            'created_at',
        )
        queryset = (
            Order.objects.filter(restaurant=restaurant)
            .select_related(
                'restaurant',
                'table_session',
                'table_session__hall',
                'table_session__table',
                'distribution_point',
                'opened_by',
                'cashier',
            )
            .only(
                'id',
                'restaurant_id',
                'restaurant__service_fee_enabled',
                'restaurant__service_fee_percent',
                'restaurant__vat_enabled',
                'restaurant__vat_percent',
                'table_session_id',
                'table_session__hall_id',
                'table_session__hall__name',
                'table_session__table_id',
                'table_session__table__name',
                'distribution_point_id',
                'opened_by_id',
                'opened_by__full_name',
                'cashier_id',
                'cashier__full_name',
                'order_number',
                'display_name',
                'channel',
                'status',
                'guest_count',
                'note',
                'subtotal',
                'total',
                'closed_at',
                'created_at',
                'updated_at',
            )
            .prefetch_related(
                Prefetch('items', queryset=item_queryset),
            )
        )
        if status_filter in {'closed', 'fiscal_closed', 'fiscal_unresolved'}:
            refund_exists = PaymentRefund.objects.filter(
                payment_id=OuterRef('pk'),
                status=PaymentRefund.Status.SUCCEEDED,
            )
            payment_queryset = (
                Payment.objects.only(
                    'id',
                    'order_id',
                    'method',
                    'amount',
                    'status',
                    'register_fiscal',
                    'paid_at',
                    'created_at',
                )
                .annotate(
                    refunds_total=Coalesce(
                        Sum('refunds__amount', filter=Q(refunds__status=PaymentRefund.Status.SUCCEEDED)),
                        Value(0),
                        output_field=IntegerField(),
                    ),
                    is_refunded=Exists(refund_exists),
                )
                .order_by('-created_at')
            )
            receipt_queryset = Receipt.objects.only(
                'id',
                'order_id',
                'payment_id',
                'kind',
                'status',
                'payload',
                'fiscal_requested_at',
                'fiscal_registered_at',
                'original_paid_at',
                'fiscal_error_code',
                'fiscal_error_message',
                'reprint_count',
                'last_reprinted_at',
                'created_at',
            ).order_by('-created_at')
            start, end = tashkent_day_bounds()
            closed_queryset = queryset.prefetch_related(
                Prefetch('payments', queryset=payment_queryset),
                Prefetch('receipts', queryset=receipt_queryset),
            ).filter(status=Order.Status.CLOSED)
            sent_fiscal_receipt = Receipt.objects.filter(
                order_id=OuterRef('pk'),
                kind=Receipt.Kind.FISCAL,
                status=Receipt.Status.SENT,
            )
            succeeded_payment = Payment.objects.filter(
                order_id=OuterRef('pk'),
                status=Payment.Status.SUCCEEDED,
            )
            if status_filter == 'closed':
                plain_queryset = closed_queryset.annotate(
                    has_sent_fiscal_receipt=Exists(sent_fiscal_receipt),
                    has_succeeded_payment=Exists(succeeded_payment),
                ).filter(
                    closed_at__gte=start,
                    closed_at__lt=end,
                    has_succeeded_payment=True,
                    has_sent_fiscal_receipt=False,
                )
                search = str(self.request.query_params.get('search') or '').strip()
                if search:
                    search_filter = (
                        Q(display_name__icontains=search)
                        | Q(cashier__full_name__icontains=search)
                        | Q(opened_by__full_name__icontains=search)
                        | Q(table_session__table__name__icontains=search)
                    )
                    if search.isdigit():
                        search_filter |= Q(order_number=int(search))
                    plain_queryset = plain_queryset.filter(search_filter).distinct()
                return plain_queryset.order_by('-closed_at')

            if status_filter == 'fiscal_closed':
                fiscal_queryset = closed_queryset.annotate(
                    has_sent_fiscal_receipt=Exists(sent_fiscal_receipt),
                ).filter(
                    closed_at__gte=start,
                    closed_at__lt=end,
                    has_sent_fiscal_receipt=True,
                )
                search = str(self.request.query_params.get('search') or '').strip()
                if search:
                    search_filter = (
                        Q(display_name__icontains=search)
                        | Q(cashier__full_name__icontains=search)
                        | Q(opened_by__full_name__icontains=search)
                        | Q(table_session__table__name__icontains=search)
                    )
                    if search.isdigit():
                        search_filter |= Q(order_number=int(search))
                    fiscal_queryset = fiscal_queryset.filter(search_filter).distinct()
                return fiscal_queryset.order_by('-closed_at', '-created_at')

            payment_receipts = Receipt.objects.filter(payment_id=OuterRef('pk'), kind=Receipt.Kind.FISCAL)
            unresolved_payment = (
                Payment.objects.filter(
                    order_id=OuterRef('pk'),
                    status=Payment.Status.SUCCEEDED,
                    register_fiscal=True,
                )
                .annotate(
                    has_fiscal_receipt=Exists(payment_receipts),
                    has_sent_fiscal_receipt=Exists(payment_receipts.filter(status=Receipt.Status.SENT)),
                    has_failed_fiscal_receipt=Exists(payment_receipts.filter(status=Receipt.Status.FAILED)),
                )
                .filter(
                    Q(has_fiscal_receipt=False)
                    | Q(has_sent_fiscal_receipt=False)
                    | Q(has_failed_fiscal_receipt=True)
                )
            )
            fiscal_queryset = closed_queryset.annotate(has_unresolved_fiscal=Exists(unresolved_payment)).filter(
                has_unresolved_fiscal=True
            )
            search = str(self.request.query_params.get('search') or '').strip()
            if search:
                search_filter = (
                    Q(display_name__icontains=search)
                    | Q(cashier__full_name__icontains=search)
                    | Q(opened_by__full_name__icontains=search)
                    | Q(table_session__table__name__icontains=search)
                    | Q(receipts__fiscal_error_message__icontains=search)
                )
                if search.isdigit():
                    search_filter |= Q(order_number=int(search))
                fiscal_queryset = fiscal_queryset.filter(search_filter).distinct()
            return fiscal_queryset.order_by('-closed_at', '-created_at')

        return self.apply_limit(queryset.filter(status__in=[Order.Status.SUBMITTED, Order.Status.READY]).order_by('-created_at'))

__all__ = [
    'CashierContextView',
    'CashShiftCloseView',
    'CashShiftOpenView',
    'FiscalShiftCloseView',
    'FiscalShiftOpenView',
    'OpenCheckListView',
]
