from django.urls import path

from apps.sales.api.pos.views.order_items import OrderItemDetailView, OrderItemListCreateView
from apps.sales.api.pos.views.orders import OrderSubmitView, PosOrderDetailView, PosOrderListCreateView

urlpatterns = [
    path('orders/', PosOrderListCreateView.as_view()),
    path('orders/<uuid:pk>/', PosOrderDetailView.as_view()),
    path('orders/<uuid:order_id>/items/', OrderItemListCreateView.as_view()),
    path('orders/items/<uuid:pk>/', OrderItemDetailView.as_view()),
    path('orders/<uuid:pk>/submit/', OrderSubmitView.as_view()),
]
