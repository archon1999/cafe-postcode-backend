from django.urls import path

from apps.local_agents.views import (
    LocalAgentAdminStatusView,
    LocalAgentPrinterCheckView,
    LocalAgentRestaurantCodeAuthView,
    LocalAgentTokenAuthView,
)

urlpatterns = [
    path('auth/restaurant-code/', LocalAgentRestaurantCodeAuthView.as_view()),
    path('auth/token/', LocalAgentTokenAuthView.as_view()),
    path('status/', LocalAgentAdminStatusView.as_view()),
    path('printer/check/', LocalAgentPrinterCheckView.as_view()),
]
