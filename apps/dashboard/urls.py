from django.urls import path

from .views import DashboardAuthLoginView, DashboardAuthLogoutView, DashboardAuthMeView, DashboardOverviewView

urlpatterns = [
    path('auth/login/', DashboardAuthLoginView.as_view()),
    path('auth/logout/', DashboardAuthLogoutView.as_view()),
    path('auth/me/', DashboardAuthMeView.as_view()),
    path('overview/', DashboardOverviewView.as_view()),
]

