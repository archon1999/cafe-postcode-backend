from django.urls import path
from apps.local_agents.support_commands import SupportCommandCatalogView, SupportCommandView

from apps.local_agents.admin_views import (
    LocalAgentFleetDiagnosticsView,
    LocalAgentFleetBulkActionView,
    LocalAgentFleetListView,
    LocalAgentFleetLogsView,
    LocalAgentFleetOutboxActionView,
    LocalAgentFleetUpdateView,
)

urlpatterns = [
    path('commands/catalog/', SupportCommandCatalogView.as_view()),
    path('<uuid:pk>/commands/', SupportCommandView.as_view()),
    path('<uuid:pk>/commands/<uuid:request_id>/', SupportCommandView.as_view()),
    path('', LocalAgentFleetListView.as_view()),
    path('bulk-action/', LocalAgentFleetBulkActionView.as_view()),
    path('<uuid:pk>/diagnostics/', LocalAgentFleetDiagnosticsView.as_view()),
    path('<uuid:pk>/logs/', LocalAgentFleetLogsView.as_view()),
    path('<uuid:pk>/outbox/<str:operation_id>/', LocalAgentFleetOutboxActionView.as_view()),
    path('<uuid:pk>/update-now/', LocalAgentFleetUpdateView.as_view()),
]
