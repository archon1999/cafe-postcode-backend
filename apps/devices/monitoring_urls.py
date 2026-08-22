from django.urls import path

from apps.devices.monitoring_views import MonitoringOverviewView


urlpatterns = [
    path('overview/', MonitoringOverviewView.as_view()),
]
