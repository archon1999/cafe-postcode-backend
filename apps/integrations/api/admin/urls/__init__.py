from django.urls import path

from apps.integrations.api.admin.views.configs import IntegrationConfigDetailView, IntegrationConfigListCreateView

urlpatterns = [
    path('configs/', IntegrationConfigListCreateView.as_view()),
    path('configs/<uuid:pk>/', IntegrationConfigDetailView.as_view()),
]
