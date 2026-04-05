from django.urls import path

from apps.kitchen.api.admin.views.tickets import KitchenTicketDetailView, KitchenTicketListView

urlpatterns = [
    path('tickets/', KitchenTicketListView.as_view()),
    path('tickets/<uuid:pk>/', KitchenTicketDetailView.as_view()),
]
