from django.urls import path

from apps.kitchen.api.pos.views import KitchenItemStatusUpdateView, KitchenQueueView, KitchenTicketDetailView, KitchenTicketStatusUpdateView

urlpatterns = [
    path('queue/', KitchenQueueView.as_view()),
    path('tickets/<uuid:pk>/', KitchenTicketDetailView.as_view()),
    path('tickets/<uuid:pk>/status/', KitchenTicketStatusUpdateView.as_view()),
    path('items/<uuid:pk>/status/', KitchenItemStatusUpdateView.as_view()),
]
