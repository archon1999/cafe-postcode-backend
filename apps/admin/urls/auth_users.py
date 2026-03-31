from django.urls import path

from apps.admin.views import (
    AdminLoginView,
    EmployeeRoleListView,
    EmployeeListCreateView,
    EmployeeRetrieveUpdateView,
    LogoutView,
    MeView,
    PermissionListView,
    RoleListCreateView,
    RoleRetrieveUpdateDestroyView,
    UserListCreateView,
    UserRetrieveUpdateView,
)

urlpatterns = [
    path('auth/login/', AdminLoginView.as_view()),
    path('auth/logout/', LogoutView.as_view()),
    path('auth/me/', MeView.as_view()),
    path('users/roles/', RoleListCreateView.as_view()),
    path('users/roles/<uuid:pk>/', RoleRetrieveUpdateDestroyView.as_view()),
    path('users/permissions/', PermissionListView.as_view()),
    path('users/', UserListCreateView.as_view()),
    path('users/<uuid:pk>/', UserRetrieveUpdateView.as_view()),
    path('employees/roles/', EmployeeRoleListView.as_view()),
    path('employees/', EmployeeListCreateView.as_view()),
    path('employees/<uuid:pk>/', EmployeeRetrieveUpdateView.as_view()),
]
