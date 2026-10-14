from django.urls import path

from .views import StaffInviteAcceptView, StaffLoginView, StaffLogoutView, StaffMeView, StaffRefreshView

urlpatterns = [
    path('invite/accept/', StaffInviteAcceptView.as_view()),
    path('login/', StaffLoginView.as_view()),
    path('refresh/', StaffRefreshView.as_view()),
    path('logout/', StaffLogoutView.as_view()),
    path('me/', StaffMeView.as_view()),
]
