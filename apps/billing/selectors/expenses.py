from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.billing.helpers import get_cash_expense_model, get_expense_category_model
from common.api.query_params import get_str_list_query_param, get_str_query_param
from common.api.scope_filters import filter_queryset_by_optional_scope

CashExpense = get_cash_expense_model()
ExpenseCategory = get_expense_category_model()


def admin_expense_category_queryset(request) -> QuerySet:
    return filter_queryset_by_optional_scope(
        ExpenseCategory.objects.all(), request
    ).order_by("sort_order", "name")


def admin_cash_expense_queryset(request) -> QuerySet:
    return (
        filter_queryset_by_optional_scope(CashExpense.objects.all(), request)
        .select_related(
            "restaurant",
            "cash_shift",
            "cash_desk",
            "category",
            "recipient",
            "created_by",
            "voided_by",
        )
        .order_by("-occurred_at", "-created_at")
    )


@dataclass(frozen=True)
class CashExpenseListFilters:
    search: str = ""
    statuses: tuple[str, ...] = ()
    category_ids: tuple[str, ...] = ()
    cash_desk_id: str = ""
    recipient_id: str = ""
    created_by_id: str = ""
    date_from: str = ""
    date_to: str = ""

    @classmethod
    def from_request(cls, request):
        params = request.query_params
        return cls(
            search=get_str_query_param(params, "search"),
            statuses=tuple(
                get_str_list_query_param(
                    params, "status_in", allowed_values={"posted", "voided"}
                )
            ),
            category_ids=tuple(
                get_str_list_query_param(
                    params, "category_id_in", aliases=("category_id",)
                )
            ),
            cash_desk_id=get_str_query_param(params, "cash_desk_id"),
            recipient_id=get_str_query_param(params, "recipient_id"),
            created_by_id=get_str_query_param(params, "created_by_id"),
            date_from=get_str_query_param(params, "date_from"),
            date_to=get_str_query_param(params, "date_to"),
        )

    def apply(self, queryset):
        if self.search:
            queryset = queryset.filter(
                Q(comment__icontains=self.search)
                | Q(category_name_snapshot__icontains=self.search)
                | Q(recipient_name_snapshot__icontains=self.search)
                | Q(created_by__full_name__icontains=self.search)
            )
        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)
        if self.category_ids:
            queryset = queryset.filter(category_id__in=self.category_ids)
        if self.cash_desk_id:
            queryset = queryset.filter(cash_desk_id=self.cash_desk_id)
        if self.recipient_id:
            queryset = queryset.filter(recipient_id=self.recipient_id)
        if self.created_by_id:
            queryset = queryset.filter(created_by_id=self.created_by_id)
        if self.date_from:
            queryset = queryset.filter(occurred_at__date__gte=self.date_from)
        if self.date_to:
            queryset = queryset.filter(occurred_at__date__lte=self.date_to)
        return queryset
