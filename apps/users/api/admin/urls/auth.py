from django.urls import path

from apps.users.api.admin.views.auth import AdminLoginView, LogoutView, MeView

urlpatterns = [
    path('login/', AdminLoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('me/', MeView.as_view()),
]
