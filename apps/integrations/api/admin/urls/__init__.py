from django.urls import path

from apps.integrations.api.admin.views import (
    FiscalDeviceListView,
    IntegrationConfigDetailView,
    IntegrationConfigListCreateView,
    MartaConnectionCheckView,
)

urlpatterns = [
    path('configs/', IntegrationConfigListCreateView.as_view()),
    path('configs/<uuid:pk>/', IntegrationConfigDetailView.as_view()),
    path('fiscal-devices/', FiscalDeviceListView.as_view()),
    path('marta/check/', MartaConnectionCheckView.as_view()),
]
