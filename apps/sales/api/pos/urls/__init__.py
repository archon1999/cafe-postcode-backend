from django.urls import path

from apps.sales.api.pos.views.marking import OrderMarkingStatusView, OrderScanMarkingView
from apps.sales.api.pos.views.order_items import BulkOrderItemCreateView, OrderItemDetailView, OrderItemListCreateView
from apps.sales.api.pos.views.orders import OrderServeReadyView, OrderSubmitView, PosOrderDetailView, PosOrderListCreateView

urlpatterns = [
    path('orders/', PosOrderListCreateView.as_view()),
    path('orders/<uuid:pk>/', PosOrderDetailView.as_view()),
    path('orders/<uuid:order_id>/items/', OrderItemListCreateView.as_view()),
    path('orders/<uuid:order_id>/items/bulk/', BulkOrderItemCreateView.as_view()),
    path('orders/<uuid:order_id>/scan-marking/', OrderScanMarkingView.as_view()),
    path('orders/<uuid:order_id>/marking-status/', OrderMarkingStatusView.as_view()),
    path('orders/items/<uuid:pk>/', OrderItemDetailView.as_view()),
    path('orders/<uuid:pk>/submit/', OrderSubmitView.as_view()),
    path('orders/<uuid:pk>/serve-ready/', OrderServeReadyView.as_view()),
]
