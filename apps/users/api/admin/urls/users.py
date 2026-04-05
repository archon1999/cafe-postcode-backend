from django.urls import path

from apps.users.api.admin.views.users import UserListCreateView, UserRetrieveUpdateView

urlpatterns = [
    path('', UserListCreateView.as_view()),
    path('<uuid:pk>/', UserRetrieveUpdateView.as_view()),
]
