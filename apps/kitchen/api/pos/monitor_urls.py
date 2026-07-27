from django.urls import path

from apps.kitchen.api.pos.views import (
    KitchenMonitorQueueView,
    TvKitchenMonitorQueueView,
    TvMonitorDiagnosticView,
    TvMonitorPairingClaimView,
    TvMonitorPairingCreateView,
    TvMonitorPairingStatusView,
)

urlpatterns = [
    path('kitchen-queue/', KitchenMonitorQueueView.as_view()),
    path('tv-kitchen-queue/', TvKitchenMonitorQueueView.as_view()),
    path('tv-diagnostics/', TvMonitorDiagnosticView.as_view()),
    path('tv-pairings/', TvMonitorPairingCreateView.as_view()),
    path('tv-pairings/<uuid:pairing_id>/', TvMonitorPairingStatusView.as_view()),
    path('tv-pairings/<uuid:pairing_id>/claim/', TvMonitorPairingClaimView.as_view()),
]
