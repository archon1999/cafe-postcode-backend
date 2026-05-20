from django.urls import path

from apps.local_agents.views import LocalAgentAdminStatusView, LocalAgentRestaurantCodeAuthView

urlpatterns = [
    path('auth/restaurant-code/', LocalAgentRestaurantCodeAuthView.as_view()),
    path('status/', LocalAgentAdminStatusView.as_view()),
]
