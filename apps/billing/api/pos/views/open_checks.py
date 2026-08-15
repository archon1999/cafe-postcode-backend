from django.core.paginator import Paginator
from django.db.models import Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.billing.api.pos.serializers import (
    OpenCheckOrderSerializer,
    OpenCheckPaginationQuerySerializer,
)
from apps.billing.helpers import (
    get_payment_model,
    get_payment_refund_model,
    get_receipt_model,
)
from apps.floor.services import annotate_zone_name_visibility
from apps.platform.services import FeatureGateService
from apps.sales.helpers import get_order_item_model, get_order_model
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.utils.date import tashkent_day_bounds

Order = get_order_model()
OrderItem = get_order_item_model()
Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()

OPEN_CHECKS_DEFAULT_LIMIT = 100
OPEN_CHECKS_MAX_LIMIT = 500


class OpenCheckListView(generics.ListAPIView):
    serializer_class = OpenCheckOrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None
    feature_gate_service_class = FeatureGateService

    def get_status_filter(self):
        return self.request.query_params.get("status", "open")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_billing"] = self.get_status_filter() in {
            "closed",
            "fiscal_closed",
            "fiscal_unresolved",
        }
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        if self.get_status_filter() in {
            "closed",
            "fiscal_closed",
            "fiscal_unresolved",
        }:
            page_number, page_size = self.get_pagination_params()
            paginator = Paginator(queryset, page_size)
            page = paginator.get_page(page_number)
            serializer = self.get_serializer(page.object_list, many=True)
            return Response(
                {
                    "data": serializer.data,
                    "count": paginator.count,
                    "page": page.number,
                    "page_size": page_size,
                    "num_pages": paginator.num_pages,
                }
            )
        return super().list(request, *args, **kwargs)

    def get_pagination_params(self):
        query_serializer = OpenCheckPaginationQuerySerializer(
            data={
                "page": self.request.query_params.get("page") or 1,
                "page_size": (
                    self.request.query_params.get("page_size")
                    or self.request.query_params.get("pageSize")
                    or 25
                ),
            }
        )
        query_serializer.is_valid(raise_exception=True)
        return (
            max(1, query_serializer.validated_data["page"]),
            min(max(query_serializer.validated_data["page_size"], 1), 100),
        )

    def get_limit(self):
        raw_limit = self.request.query_params.get("limit")
        if raw_limit is None:
            return OPEN_CHECKS_DEFAULT_LIMIT
        if raw_limit == "all":
            return None
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"limit": 'Limit must be a positive integer or "all".'}
            ) from exc
        if limit < 1:
            raise ValidationError(
                {"limit": 'Limit must be a positive integer or "all".'}
            )
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
        item_queryset = OrderItem.objects.select_related(
            "catalog_item", "prep_station"
        ).only(
            "id",
            "order_id",
            "catalog_item_id",
            "catalog_item__name",
            "catalog_item__name_uz",
            "catalog_item__name_uz_crl",
            "catalog_item__name_ru",
            "prep_station_id",
            "prep_station__name",
            "prep_station__name_uz",
            "prep_station__name_uz_crl",
            "prep_station__name_ru",
            "quantity",
            "sale_unit",
            "unit_price",
            "line_total",
            "status",
            "note",
            "created_at",
        )
        queryset = (
            annotate_zone_name_visibility(Order.objects.filter(restaurant=restaurant))
            .select_related(
                "restaurant",
                "table_session",
                "table_session__hall",
                "table_session__hall__zone_or_cabin",
                "table_session__table",
                "distribution_point",
                "opened_by",
                "cashier",
            )
            .only(
                "id",
                "restaurant_id",
                "restaurant__name",
                "restaurant__name_uz",
                "restaurant__name_uz_crl",
                "restaurant__name_ru",
                "restaurant__service_fee_enabled",
                "restaurant__service_fee_percent",
                "restaurant__vat_enabled",
                "restaurant__vat_percent",
                "table_session_id",
                "table_session__hall_id",
                "table_session__hall__name",
                "table_session__hall__name_uz",
                "table_session__hall__name_uz_crl",
                "table_session__hall__name_ru",
                "table_session__hall__zone_or_cabin_id",
                "table_session__hall__zone_or_cabin__name",
                "table_session__hall__zone_or_cabin__name_uz",
                "table_session__hall__zone_or_cabin__name_uz_crl",
                "table_session__hall__zone_or_cabin__name_ru",
                "table_session__table_id",
                "table_session__table__name",
                "table_session__table__table_number",
                "distribution_point_id",
                "opened_by_id",
                "opened_by__full_name",
                "cashier_id",
                "cashier__full_name",
                "order_number",
                "display_name",
                "channel",
                "status",
                "guest_count",
                "note",
                "subtotal",
                "calculated_total",
                "restaurant_service_fee_percent",
                "hall_service_fee_percent",
                "table_service_fee_percent",
                "total",
                "closed_at",
                "created_at",
                "updated_at",
            )
            .prefetch_related(Prefetch("items", queryset=item_queryset))
        )
        if status_filter in {"closed", "fiscal_closed", "fiscal_unresolved"}:
            return self._closed_queryset(queryset, status_filter)
        return self.apply_limit(
            queryset.filter(
                status__in=[Order.Status.SUBMITTED, Order.Status.READY]
            ).order_by("-created_at")
        )

    def _closed_queryset(self, queryset, status_filter):
        refund_exists = PaymentRefund.objects.filter(
            payment_id=OuterRef("pk"), status=PaymentRefund.Status.SUCCEEDED
        )
        payment_queryset = (
            Payment.objects.only(
                "id",
                "order_id",
                "method",
                "amount",
                "cash_amount",
                "card_amount",
                "fiscal_cash_amount",
                "fiscal_card_amount",
                "fiscal_adjustment_reason",
                "status",
                "register_fiscal",
                "paid_at",
                "created_at",
            )
            .annotate(
                refunds_total=Coalesce(
                    Sum(
                        "refunds__amount",
                        filter=Q(refunds__status=PaymentRefund.Status.SUCCEEDED),
                    ),
                    Value(0),
                    output_field=IntegerField(),
                ),
                is_refunded=Exists(refund_exists),
            )
            .order_by("-created_at")
        )
        receipt_queryset = Receipt.objects.only(
            "id",
            "order_id",
            "payment_id",
            "kind",
            "status",
            "payload",
            "fiscal_requested_at",
            "fiscal_registered_at",
            "original_paid_at",
            "fiscal_error_code",
            "fiscal_error_message",
            "reprint_count",
            "last_reprinted_at",
            "created_at",
        ).order_by("-created_at")
        start, end = tashkent_day_bounds()
        closed_queryset = queryset.prefetch_related(
            Prefetch("payments", queryset=payment_queryset),
            Prefetch("receipts", queryset=receipt_queryset),
        ).filter(status=Order.Status.CLOSED)
        sent_fiscal_receipt = Receipt.objects.filter(
            order_id=OuterRef("pk"),
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
        )
        if status_filter == "closed":
            succeeded_payment = Payment.objects.filter(
                order_id=OuterRef("pk"), status=Payment.Status.SUCCEEDED
            )
            result = closed_queryset.annotate(
                has_sent_fiscal_receipt=Exists(sent_fiscal_receipt),
                has_succeeded_payment=Exists(succeeded_payment),
            ).filter(
                closed_at__gte=start,
                closed_at__lt=end,
                has_succeeded_payment=True,
                has_sent_fiscal_receipt=False,
            )
            return self._apply_search(result).order_by("-closed_at")

        if status_filter == "fiscal_closed":
            result = closed_queryset.annotate(
                has_sent_fiscal_receipt=Exists(sent_fiscal_receipt)
            ).filter(
                closed_at__gte=start,
                closed_at__lt=end,
                has_sent_fiscal_receipt=True,
            )
            return self._apply_search(result).order_by("-closed_at", "-created_at")

        payment_receipts = Receipt.objects.filter(
            payment_id=OuterRef("pk"), kind=Receipt.Kind.FISCAL
        )
        unresolved_payment = (
            Payment.objects.filter(
                order_id=OuterRef("pk"),
                status=Payment.Status.SUCCEEDED,
                register_fiscal=True,
            )
            .annotate(
                has_fiscal_receipt=Exists(payment_receipts),
                has_sent_fiscal_receipt=Exists(
                    payment_receipts.filter(status=Receipt.Status.SENT)
                ),
                has_failed_fiscal_receipt=Exists(
                    payment_receipts.filter(status=Receipt.Status.FAILED)
                ),
            )
            .filter(
                Q(has_fiscal_receipt=False)
                | Q(has_sent_fiscal_receipt=False)
                | Q(has_failed_fiscal_receipt=True)
            )
        )
        result = closed_queryset.annotate(
            has_unresolved_fiscal=Exists(unresolved_payment)
        ).filter(has_unresolved_fiscal=True)
        return self._apply_search(result, include_fiscal_error=True).order_by(
            "-closed_at", "-created_at"
        )

    def _apply_search(self, queryset, *, include_fiscal_error=False):
        search = str(self.request.query_params.get("search") or "").strip()
        if not search:
            return queryset
        search_filter = (
            Q(display_name__icontains=search)
            | Q(cashier__full_name__icontains=search)
            | Q(opened_by__full_name__icontains=search)
            | Q(table_session__table__name__icontains=search)
        )
        if include_fiscal_error:
            search_filter |= Q(receipts__fiscal_error_message__icontains=search)
        if search.isdigit():
            search_filter |= Q(order_number=int(search))
        return queryset.filter(search_filter).distinct()
