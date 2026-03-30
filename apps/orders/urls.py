from django.urls import path

from .views import (
    CashierContextView,
    CashShiftCloseView,
    CashShiftOpenView,
    OpenCheckListView,
    OrderItemDetailView,
    OrderItemListCreateView,
    OrderSubmitView,
    PaymentCreateView,
    PaymentRefundView,
    PosOrderDetailView,
    PosOrderListCreateView,
    ReceiptReprintView,
)

urlpatterns = [
    path('pos/orders/', PosOrderListCreateView.as_view()),
    path('pos/orders/<uuid:pk>/', PosOrderDetailView.as_view()),
    path('pos/orders/<uuid:order_id>/items/', OrderItemListCreateView.as_view()),
    path('pos/orders/items/<uuid:pk>/', OrderItemDetailView.as_view()),
    path('pos/orders/<uuid:pk>/submit/', OrderSubmitView.as_view()),
    path('pos/cashier/context/', CashierContextView.as_view()),
    path('pos/cashier/shifts/open/', CashShiftOpenView.as_view()),
    path('pos/cashier/shifts/current/close/', CashShiftCloseView.as_view()),
    path('pos/payments/open-checks/', OpenCheckListView.as_view()),
    path('pos/payments/orders/<uuid:pk>/pay/', PaymentCreateView.as_view()),
    path('pos/payments/<uuid:pk>/refund/', PaymentRefundView.as_view()),
    path('pos/receipts/<uuid:pk>/reprint/', ReceiptReprintView.as_view()),
]
