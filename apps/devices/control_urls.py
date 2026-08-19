from django.urls import path

from apps.devices.control_views import (
    ControlBranchDeviceListView,
    ControlBranchListView,
    ControlDeviceRevokeView,
    ControlPairingApproveView,
    ControlPairingRejectView,
    ControlPairingResolveView,
)


urlpatterns = [
    path('branches/', ControlBranchListView.as_view()),
    path('branches/<uuid:restaurant_id>/devices/', ControlBranchDeviceListView.as_view()),
    path(
        'branches/<uuid:restaurant_id>/devices/<uuid:device_id>/revoke/',
        ControlDeviceRevokeView.as_view(),
    ),
    path('pairings/resolve/', ControlPairingResolveView.as_view()),
    path(
        'branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/approve/',
        ControlPairingApproveView.as_view(),
    ),
    path(
        'branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/reject/',
        ControlPairingRejectView.as_view(),
    ),
]
