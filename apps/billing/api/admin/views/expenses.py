from django.db.models import Sum
from django.db.models.functions import Coalesce
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api.admin.serializers import AdminCashExpenseSerializer, AdminExpenseCategorySerializer
from apps.billing.selectors.expenses import (
    CashExpenseListFilters,
    admin_cash_expense_queryset,
    admin_expense_category_queryset,
)
from apps.billing.serializers import CashExpenseVoidSerializer
from apps.billing.services import CashExpenseService
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant


class ExpenseCategoryListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = AdminExpenseCategorySerializer
    pagination_class = None

    def get_queryset(self):
        queryset = admin_expense_category_queryset(self.request)
        is_active = self.request.query_params.get('is_active') or self.request.query_params.get('isActive')
        if is_active in ('true', '1'):
            queryset = queryset.filter(is_active=True)
        elif is_active in ('false', '0'):
            queryset = queryset.filter(is_active=False)
        return queryset

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request), created_by=self.request.user)


class ExpenseCategoryDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = AdminExpenseCategorySerializer

    def get_queryset(self):
        return admin_expense_category_queryset(self.request)


class CashExpenseListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminCashExpenseSerializer

    def get_queryset(self):
        return CashExpenseListFilters.from_request(self.request).apply(admin_cash_expense_queryset(self.request))

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        posted_total = queryset.filter(status='posted').aggregate(total=Coalesce(Sum('amount'), 0))['total']
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['postedTotal'] = posted_total
            return response
        serializer = self.get_serializer(queryset, many=True)
        return Response({'postedTotal': posted_total, 'data': serializer.data})


class CashExpenseDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminCashExpenseSerializer

    def get_queryset(self):
        return admin_cash_expense_queryset(self.request)


class CashExpenseVoidView(AdminPermissionRequiredMixin, APIView):
    service_class = CashExpenseService

    def post(self, request, pk):
        expense = generics.get_object_or_404(admin_cash_expense_queryset(request), pk=pk)
        serializer = CashExpenseVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense = self.service_class().void_expense(
            expense=expense,
            user=request.user,
            reason=serializer.validated_data['reason'],
        )
        return Response(AdminCashExpenseSerializer(expense).data)


__all__ = [
    'CashExpenseDetailView',
    'CashExpenseListView',
    'CashExpenseVoidView',
    'ExpenseCategoryDetailView',
    'ExpenseCategoryListCreateView',
]
