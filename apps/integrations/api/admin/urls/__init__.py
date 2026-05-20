from django.urls import path

from apps.integrations.api.admin.views import (
    FiscalDeviceListView,
    IntegrationConfigDetailView,
    IntegrationConfigListCreateView,
)

urlpatterns = [
    path('configs/', IntegrationConfigListCreateView.as_view()),
    path('configs/<uuid:pk>/', IntegrationConfigDetailView.as_view()),
    path('fiscal-devices/', FiscalDeviceListView.as_view()),
]
