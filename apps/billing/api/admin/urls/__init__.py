from django.urls import path

from apps.billing.api.admin.views.payments import PaymentDetailView, PaymentListView
from apps.billing.api.admin.views.receipts import ReceiptDetailView, ReceiptListView

urlpatterns = [
    path('payments/', PaymentListView.as_view()),
    path('payments/<uuid:pk>/', PaymentDetailView.as_view()),
    path('receipts/', ReceiptListView.as_view()),
    path('receipts/<uuid:pk>/', ReceiptDetailView.as_view()),
]
