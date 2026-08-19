from django.urls import path

from apps.devices.views import (
    DeviceDetailView,
    DeviceListView,
    DeviceMigrationSummaryView,
    DevicePairingAdminListView,
    DevicePairingApproveView,
    DevicePairingRejectView,
    DeviceRevokeView,
)


urlpatterns = [
    path('', DeviceListView.as_view()),
    path('migration-summary/', DeviceMigrationSummaryView.as_view()),
    path('pairings/', DevicePairingAdminListView.as_view()),
    path('pairings/<uuid:pairing_id>/approve/', DevicePairingApproveView.as_view()),
    path('pairings/<uuid:pairing_id>/reject/', DevicePairingRejectView.as_view()),
    path('<uuid:pk>/', DeviceDetailView.as_view()),
    path('<uuid:pk>/revoke/', DeviceRevokeView.as_view()),
]
