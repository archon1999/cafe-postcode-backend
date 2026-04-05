from django.urls import path

from apps.sales.api.admin.views.order_item_notes import OrderItemNoteDetailView, OrderItemNoteListView
from apps.sales.api.admin.views.order_items import OrderItemDetailView, OrderItemListView
from apps.sales.api.admin.views.orders import OrderDetailView, OrderListView

urlpatterns = [
    path('orders/', OrderListView.as_view()),
    path('orders/<uuid:pk>/', OrderDetailView.as_view()),
    path('order-items/', OrderItemListView.as_view()),
    path('order-items/<uuid:pk>/', OrderItemDetailView.as_view()),
    path('order-item-notes/', OrderItemNoteListView.as_view()),
    path('order-item-notes/<uuid:pk>/', OrderItemNoteDetailView.as_view()),
]
