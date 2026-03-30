from django.urls import path

from .views import KitchenItemStatusUpdateView, KitchenQueueView, KitchenTicketDetailView, KitchenTicketStatusUpdateView

urlpatterns = [
    path('pos/kitchen/queue/', KitchenQueueView.as_view()),
    path('pos/kitchen/tickets/<uuid:pk>/', KitchenTicketDetailView.as_view()),
    path('pos/kitchen/tickets/<uuid:pk>/status/', KitchenTicketStatusUpdateView.as_view()),
    path('pos/kitchen/items/<uuid:pk>/status/', KitchenItemStatusUpdateView.as_view()),
]
