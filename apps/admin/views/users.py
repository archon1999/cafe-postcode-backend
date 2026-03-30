from rest_framework import generics

from apps.accounts.models import Permission, Role
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import PermissionSerializer, RoleSerializer, UserSerializer
from apps.admin.support import (
    AdminUserQuerysetMixin,
    PermissionListFilters,
    RoleListFilters,
    prevent_system_role_delete,
)
from common.api.scopes import get_request_restaurant


class PermissionListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = PermissionSerializer

    def get_permission_code(self):
        return 'tariffs.view'

    def get_queryset(self):
        queryset = Permission.objects.all()
        return PermissionListFilters.from_request(self.request).apply(queryset)


class RoleListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RoleSerializer

    def get_permission_code(self):
        return 'tariffs.view' if self.request.method == 'GET' else 'users.manage'

    def get_queryset(self):
        queryset = Role.objects.prefetch_related('permissions').all()
        return RoleListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(is_system=False)


class RoleRetrieveUpdateDestroyView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Role.objects.prefetch_related('permissions').all()
    serializer_class = RoleSerializer

    def get_permission_code(self):
        return 'tariffs.view' if self.request.method == 'GET' else 'users.manage'

    def perform_destroy(self, instance):
        prevent_system_role_delete(instance)
        instance.delete()


class UserListCreateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_code = 'users.manage'

    def get_queryset(self):
        return self.get_filtered_user_queryset()

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)


class UserRetrieveUpdateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_code = 'users.manage'

    def get_queryset(self):
        return self.get_user_queryset()
