from django.urls import path

from apps.devices.views import (
    DeviceLeaseRenewView,
    DeviceMeView,
    DevicePairingCreateView,
    DevicePairingStatusView,
    LegacyPosMigrationView,
    LegacyTvMigrationView,
)


urlpatterns = [
    path('pairings/', DevicePairingCreateView.as_view()),
    path('pairings/<uuid:pairing_id>/status/', DevicePairingStatusView.as_view()),
    path('me/', DeviceMeView.as_view()),
    path('lease/renew/', DeviceLeaseRenewView.as_view()),
    path('legacy-pos-migration/', LegacyPosMigrationView.as_view()),
    path('legacy-tv-migration/', LegacyTvMigrationView.as_view()),
]
