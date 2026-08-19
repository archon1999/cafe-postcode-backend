from django.urls import path

from apps.users.api.admin.views.auth import (
    AdminLockView,
    AdminLoginView,
    AdminRefreshView,
    AdminUnlockView,
    LogoutView,
    MeView,
    MFAChallengeView,
    MFAEnrollmentConfirmView,
    MFAEnrollmentStartView,
    MFAStepUpView,
)

urlpatterns = [
    path('login/', AdminLoginView.as_view()),
    path('refresh/', AdminRefreshView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('lock/', AdminLockView.as_view()),
    path('unlock/', AdminUnlockView.as_view()),
    path('mfa/enrollment/start/', MFAEnrollmentStartView.as_view()),
    path('mfa/enrollment/confirm/', MFAEnrollmentConfirmView.as_view()),
    path('mfa/challenge/', MFAChallengeView.as_view()),
    path('mfa/step-up/', MFAStepUpView.as_view()),
    path('me/', MeView.as_view()),
]
