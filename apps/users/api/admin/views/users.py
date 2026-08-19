from rest_framework import generics

from apps.users.api.admin.serializers import UserSerializer
from apps.users.api.admin.permissions import PlatformPermissionRequiredMixin
from apps.users.selectors.users import AdminUserQuerysetMixin


class UserListCreateView(PlatformPermissionRequiredMixin, AdminUserQuerysetMixin, generics.ListCreateAPIView):
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


class UserRetrieveUpdateView(PlatformPermissionRequiredMixin, AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    user_surface = 'system'

    def get_queryset(self):
        return self.get_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context

__all__ = ['UserListCreateView', 'UserRetrieveUpdateView']
