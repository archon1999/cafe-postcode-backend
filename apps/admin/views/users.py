from rest_framework import generics

from apps.accounts.models import Permission, Role
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import (
    EmployeeSerializer,
    PermissionOptionSerializer,
    PermissionSerializer,
    RoleSerializer,
    UserSerializer,
)
from apps.admin.support import (
    AdminUserQuerysetMixin,
    PermissionListFilters,
    RoleListFilters,
    employee_role_queryset,
    scoped_role_queryset,
    prevent_system_role_delete,
)
from apps.admin.support.business_partner import activation_permission_queryset, activation_role_queryset
from common.api.scopes import get_request_restaurant


class PermissionListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = PermissionSerializer

    def get_queryset(self):
        queryset = Permission.objects.prefetch_related('endpoints').all()
        return PermissionListFilters.from_request(self.request).apply(queryset)


class PermissionOptionsView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = PermissionOptionSerializer
    pagination_class = None

    def get_queryset(self):
        if self.request.user.get_business_partner_scope() is not None and not self.request.user.is_superuser:
            return activation_permission_queryset()
        return Permission.objects.order_by('code').all()


class RoleListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        if self.request.user.get_business_partner_scope() is not None and not self.request.user.is_superuser:
            queryset = activation_role_queryset()
            return RoleListFilters.from_request(self.request).apply(queryset)
        queryset = scoped_role_queryset(self.request)
        return RoleListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(is_system=False)


class EmployeeRoleListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        queryset = employee_role_queryset(self.request)
        return RoleListFilters.from_request(self.request).apply(queryset)


class RoleRetrieveUpdateDestroyView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        return scoped_role_queryset(self.request)

    def perform_destroy(self, instance):
        prevent_system_role_delete(instance)
        instance.delete()


class UserListCreateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = UserSerializer
    user_surface = 'system'

    def get_queryset(self):
        return self.get_filtered_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context

    def perform_create(self, serializer):
        serializer.save()


class UserRetrieveUpdateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    user_surface = 'system'

    def get_queryset(self):
        return self.get_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context


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
