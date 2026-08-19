from django.urls import path

from apps.devices.views import SecurityEventAcknowledgeView, SecurityEventListView


urlpatterns = [
    path('', SecurityEventListView.as_view()),
    path('<uuid:pk>/acknowledge/', SecurityEventAcknowledgeView.as_view()),
]
