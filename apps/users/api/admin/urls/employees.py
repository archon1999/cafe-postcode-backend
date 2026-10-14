from django.urls import path

from apps.users.api.admin.views.employees import EmployeeListCreateView, EmployeeRetrieveUpdateView, EmployeeRoleListView, EmployeeStaffInviteView

urlpatterns = [
    path('roles/', EmployeeRoleListView.as_view()),
    path('', EmployeeListCreateView.as_view()),
    path('<uuid:pk>/', EmployeeRetrieveUpdateView.as_view()),
    path('<uuid:pk>/staff-invite/', EmployeeStaffInviteView.as_view()),
]
