from django.urls import path

from apps.devices.views import SecurityEventAcknowledgeView, SecurityEventListView, SecurityEventsBulkAcknowledgeView


urlpatterns = [
    path('bulk-acknowledge/', SecurityEventsBulkAcknowledgeView.as_view()),
    path('', SecurityEventListView.as_view()),
    path('<uuid:pk>/acknowledge/', SecurityEventAcknowledgeView.as_view()),
]
