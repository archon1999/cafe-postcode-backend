from django.urls import path

from apps.dashboard.api.views.auth import DashboardAuthLoginView, DashboardAuthLogoutView, DashboardAuthMeView
from apps.dashboard.api.views.details import (
    DashboardOpenChecksView,
    DashboardShiftView,
    DashboardStaffView,
    DashboardTopItemsView,
)
from apps.dashboard.api.views.overview import DashboardOverviewView

urlpatterns = [
    path('auth/login/', DashboardAuthLoginView.as_view()),
    path('auth/logout/', DashboardAuthLogoutView.as_view()),
    path('auth/me/', DashboardAuthMeView.as_view()),
    path('overview/', DashboardOverviewView.as_view()),
    path('open-checks/', DashboardOpenChecksView.as_view()),
    path('top-items/', DashboardTopItemsView.as_view()),
    path('staff/', DashboardStaffView.as_view()),
    path('shifts/', DashboardShiftView.as_view()),
]
