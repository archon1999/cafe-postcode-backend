from django.urls import path

from apps.local_agents.print_documents import LocalAgentPrintDocumentView
from apps.local_agents.releases import LocalAgentLatestReleaseView
from apps.local_agents.security_events import LocalAgentSecurityEventBatchView
from apps.local_agents.sync import (
    LocalAgentBootstrapView,
    LocalAgentConfigurationView,
    LocalAgentOperationalStateView,
    LocalAgentPOSDeviceStateView,
)
from apps.local_agents.mutations import LocalAgentMutationPushView
from apps.local_agents.views import (
    LocalAgentAdminStatusView,
    LocalAgentDiagnosticsView,
    LocalAgentLogsView,
    LocalAgentPrinterCheckView,
    LocalAgentTokenAuthView,
    LocalAgentUpdateNowView,
)
from apps.local_agents.device_views import LocalAgentDeviceMigrationView

urlpatterns = [
    path('auth/token/', LocalAgentTokenAuthView.as_view()),
    path('device-migration/', LocalAgentDeviceMigrationView.as_view()),
    path('print-documents/<uuid:document_id>/', LocalAgentPrintDocumentView.as_view()),
    path('releases/latest/', LocalAgentLatestReleaseView.as_view()),
    path('sync/bootstrap/', LocalAgentBootstrapView.as_view()),
    path('sync/configuration/', LocalAgentConfigurationView.as_view()),
    path('sync/operational/', LocalAgentOperationalStateView.as_view()),
    path('sync/pos-device-state/', LocalAgentPOSDeviceStateView.as_view()),
    path('sync/mutations/', LocalAgentMutationPushView.as_view()),
    path('security-events/batch/', LocalAgentSecurityEventBatchView.as_view()),
    path('status/', LocalAgentAdminStatusView.as_view()),
    path('diagnostics/', LocalAgentDiagnosticsView.as_view()),
    path('logs/', LocalAgentLogsView.as_view()),
    path('update-now/', LocalAgentUpdateNowView.as_view()),
    path('printer/check/', LocalAgentPrinterCheckView.as_view()),
]
