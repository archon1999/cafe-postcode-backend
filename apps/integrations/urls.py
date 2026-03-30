from django.urls import path

from .views import IntegrationConfigDetailView, IntegrationConfigListCreateView

urlpatterns = [
    path('admin/integrations/configs/', IntegrationConfigListCreateView.as_view()),
    path('admin/integrations/configs/<uuid:pk>/', IntegrationConfigDetailView.as_view()),
]
