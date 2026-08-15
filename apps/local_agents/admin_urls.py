from django.urls import path

from apps.local_agents.admin_views import (
    LocalAgentFleetDiagnosticsView,
    LocalAgentFleetBulkActionView,
    LocalAgentFleetListView,
    LocalAgentFleetLogsView,
    LocalAgentFleetOutboxActionView,
    LocalAgentFleetUpdateView,
)

urlpatterns = [
    path('', LocalAgentFleetListView.as_view()),
    path('bulk-action/', LocalAgentFleetBulkActionView.as_view()),
    path('<uuid:pk>/diagnostics/', LocalAgentFleetDiagnosticsView.as_view()),
    path('<uuid:pk>/logs/', LocalAgentFleetLogsView.as_view()),
    path('<uuid:pk>/outbox/<str:operation_id>/', LocalAgentFleetOutboxActionView.as_view()),
    path('<uuid:pk>/update-now/', LocalAgentFleetUpdateView.as_view()),
]
