from django.urls import path

from apps.billing.api.pos.views.context import (
    CashierContextView,
    CashShiftCloseView,
    CashShiftOpenView,
    FiscalShiftCloseView,
    FiscalShiftOpenView,
    OpenCheckListView,
)
from apps.billing.api.pos.views.payments import PaymentCreateView, PaymentFiscalRetryView, PaymentRefundView
from apps.billing.api.pos.views.receipts import (
    OrderPrebillPrintView,
    ReceiptPrintResultView,
    ReceiptReprintView,
)

urlpatterns = [
    path('context/', CashierContextView.as_view()),
    path('shifts/open/', CashShiftOpenView.as_view()),
    path('shifts/current/close/', CashShiftCloseView.as_view()),
    path('fiscal-shifts/open/', FiscalShiftOpenView.as_view()),
    path('fiscal-shifts/close/', FiscalShiftCloseView.as_view()),
    path('open-checks/', OpenCheckListView.as_view()),
    path('orders/<uuid:pk>/prebill/print/', OrderPrebillPrintView.as_view()),
    path('orders/<uuid:pk>/pay/', PaymentCreateView.as_view()),
    path('payments/<uuid:pk>/retry-fiscal/', PaymentFiscalRetryView.as_view()),
    path('<uuid:pk>/refund/', PaymentRefundView.as_view()),
    path('receipts/<uuid:pk>/print-result/', ReceiptPrintResultView.as_view()),
    path('receipts/<uuid:pk>/reprint/', ReceiptReprintView.as_view()),
]
