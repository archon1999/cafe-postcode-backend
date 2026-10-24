from django.urls import path
from apps.platform.api.admin.views.ai_usage import AIUsageRequestsView, AIUsageSummaryView

urlpatterns = [
    path('summary/', AIUsageSummaryView.as_view(), name='admin-ai-usage-summary'),
    path('requests/', AIUsageRequestsView.as_view(), name='admin-ai-usage-requests'),
]
