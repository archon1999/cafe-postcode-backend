from django.urls import path

from apps.users.api.admin.views.permissions import PermissionListView, PermissionOptionsView

urlpatterns = [
    path('', PermissionListView.as_view()),
    path('options/', PermissionOptionsView.as_view()),
]
