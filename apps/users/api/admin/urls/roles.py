from django.urls import path

from apps.users.api.admin.views.roles import RoleListCreateView, RoleRetrieveUpdateDestroyView

urlpatterns = [
    path('', RoleListCreateView.as_view()),
    path('<uuid:pk>/', RoleRetrieveUpdateDestroyView.as_view()),
]
