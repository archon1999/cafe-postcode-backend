from django.urls import path

from apps.billing.api.admin.views.payments import PaymentDetailView, PaymentFiscalRetryView, PaymentListView
from apps.billing.api.admin.views.receipts import ReceiptDetailView, ReceiptListView
from apps.billing.api.admin.views.expenses import (
    CashExpenseDetailView,
    CashExpenseListView,
    CashExpenseVoidView,
    ExpenseCategoryDetailView,
    ExpenseCategoryListCreateView,
)

urlpatterns = [
    path('expense-categories/', ExpenseCategoryListCreateView.as_view()),
    path('expense-categories/<uuid:pk>/', ExpenseCategoryDetailView.as_view()),
    path('expenses/', CashExpenseListView.as_view()),
    path('expenses/<uuid:pk>/', CashExpenseDetailView.as_view()),
    path('expenses/<uuid:pk>/void/', CashExpenseVoidView.as_view()),
    path('payments/', PaymentListView.as_view()),
    path('payments/<uuid:pk>/', PaymentDetailView.as_view()),
    path('payments/<uuid:pk>/retry-fiscal/', PaymentFiscalRetryView.as_view()),
    path('receipts/', ReceiptListView.as_view()),
    path('receipts/<uuid:pk>/', ReceiptDetailView.as_view()),
]
