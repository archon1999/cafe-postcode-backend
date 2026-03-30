from django.urls import path

from apps.admin.views import (
    IntegrationConfigDetailView,
    IntegrationConfigListCreateView,
    KitchenTicketDetailView,
    KitchenTicketListView,
    OrderDetailView,
    OrderItemDetailView,
    OrderItemListView,
    OrderItemNoteDetailView,
    OrderItemNoteListView,
    OrderListView,
    PaymentDetailView,
    PaymentListView,
    ReceiptDetailView,
    ReceiptListView,
)

urlpatterns = [
    path('orders/', OrderListView.as_view()),
    path('orders/<uuid:pk>/', OrderDetailView.as_view()),
    path('order-items/', OrderItemListView.as_view()),
    path('order-items/<uuid:pk>/', OrderItemDetailView.as_view()),
    path('order-item-notes/', OrderItemNoteListView.as_view()),
    path('order-item-notes/<uuid:pk>/', OrderItemNoteDetailView.as_view()),
    path('payments/', PaymentListView.as_view()),
    path('payments/<uuid:pk>/', PaymentDetailView.as_view()),
    path('receipts/', ReceiptListView.as_view()),
    path('receipts/<uuid:pk>/', ReceiptDetailView.as_view()),
    path('kitchen/tickets/', KitchenTicketListView.as_view()),
    path('kitchen/tickets/<uuid:pk>/', KitchenTicketDetailView.as_view()),
    path('integrations/configs/', IntegrationConfigListCreateView.as_view()),
    path('integrations/configs/<uuid:pk>/', IntegrationConfigDetailView.as_view()),
]
