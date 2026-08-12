from django.urls import path

from apps.billing.api.pos.views.context import (
    CashierContextView,
    CashShiftCloseView,
    CashShiftOpenView,
    CashShiftReportPrintView,
    FiscalShiftCloseView,
    FiscalShiftOpenView,
    OpenCheckListView,
)
from apps.billing.api.pos.views.payments import (
    MartaCardPaymentInitiateView,
    MartaTerminalResultView,
    PaymentCreateView,
    PaymentFiscalRetryView,
    PaymentPrintDocumentView,
    PaymentRefundView,
)
from apps.billing.api.pos.views.expenses import (
    PosCashExpenseListCreateView,
    PosCashExpenseVoidView,
    PosExpenseCategoryListView,
)
from apps.billing.api.pos.views.prechecks import OrderPrecheckPrintDocumentView

urlpatterns = [
    path('context/', CashierContextView.as_view()),
    path('shifts/open/', CashShiftOpenView.as_view()),
    path('shifts/current/close/', CashShiftCloseView.as_view()),
    path('shifts/current/print-report/', CashShiftReportPrintView.as_view()),
    path('expense-categories/', PosExpenseCategoryListView.as_view()),
    path('shifts/current/expenses/', PosCashExpenseListCreateView.as_view()),
    path('expenses/<uuid:pk>/void/', PosCashExpenseVoidView.as_view()),
    path('fiscal-shifts/open/', FiscalShiftOpenView.as_view()),
    path('fiscal-shifts/close/', FiscalShiftCloseView.as_view()),
    path('open-checks/', OpenCheckListView.as_view()),
    path('orders/<uuid:pk>/precheck/print-document/', OrderPrecheckPrintDocumentView.as_view()),
    path('orders/<uuid:pk>/pay/', PaymentCreateView.as_view()),
    path('orders/<uuid:pk>/card-payments/initiate/', MartaCardPaymentInitiateView.as_view()),
    path('payments/<uuid:pk>/terminal-result/', MartaTerminalResultView.as_view()),
    path('payments/<uuid:pk>/retry-fiscal/', PaymentFiscalRetryView.as_view()),
    path('payments/<uuid:pk>/print-document/', PaymentPrintDocumentView.as_view()),
    path('<uuid:pk>/refund/', PaymentRefundView.as_view()),
]
