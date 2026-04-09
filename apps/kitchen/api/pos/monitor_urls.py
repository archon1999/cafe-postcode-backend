from django.urls import path

from apps.kitchen.api.pos.views import KitchenMonitorQueueView

urlpatterns = [
    path('kitchen-queue/', KitchenMonitorQueueView.as_view()),
]
