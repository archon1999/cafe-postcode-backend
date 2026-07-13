from django.urls import path

from apps.local_agents.print_documents import LocalAgentPrintDocumentView
from apps.local_agents.releases import LocalAgentLatestReleaseView
from apps.local_agents.sync import LocalAgentBootstrapView
from apps.local_agents.mutations import LocalAgentMutationPushView
from apps.local_agents.views import (
    LocalAgentAdminStatusView,
    LocalAgentDiagnosticsView,
    LocalAgentEnrollView,
    LocalAgentEnrollmentPreflightView,
    LocalAgentEnrollmentTokenView,
    LocalAgentPrinterCheckView,
    LocalAgentTokenAuthView,
    LocalAgentUpdateNowView,
)

urlpatterns = [
    path('auth/enroll/', LocalAgentEnrollView.as_view()),
    path('auth/enrollment/preflight/', LocalAgentEnrollmentPreflightView.as_view()),
    path('enrollment-token/', LocalAgentEnrollmentTokenView.as_view()),
    path('auth/token/', LocalAgentTokenAuthView.as_view()),
    path('print-documents/<uuid:document_id>/', LocalAgentPrintDocumentView.as_view()),
    path('releases/latest/', LocalAgentLatestReleaseView.as_view()),
    path('sync/bootstrap/', LocalAgentBootstrapView.as_view()),
    path('sync/mutations/', LocalAgentMutationPushView.as_view()),
    path('status/', LocalAgentAdminStatusView.as_view()),
    path('diagnostics/', LocalAgentDiagnosticsView.as_view()),
    path('update-now/', LocalAgentUpdateNowView.as_view()),
    path('printer/check/', LocalAgentPrinterCheckView.as_view()),
]
