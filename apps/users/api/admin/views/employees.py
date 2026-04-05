from rest_framework import generics

from apps.users.api.admin.serializers import EmployeeSerializer, RoleSerializer
from apps.users.selectors.users import AdminUserQuerysetMixin, RoleListFilters, employee_role_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant


class EmployeeRoleListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        queryset = employee_role_queryset(self.request)
        return RoleListFilters.from_request(self.request).apply(queryset)


class EmployeeListCreateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = EmployeeSerializer
    user_surface = 'employee'

    def get_queryset(self):
        return self.get_filtered_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class EmployeeRetrieveUpdateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    serializer_class = EmployeeSerializer
    user_surface = 'employee'

    def get_queryset(self):
        return self.get_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context

__all__ = ['EmployeeListCreateView', 'EmployeeRetrieveUpdateView', 'EmployeeRoleListView']
