from rest_framework import generics, permissions

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch, get_request_restaurant


class UserListCreateView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'users.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return (
            User.objects.filter(restaurant=restaurant)
            .select_related('role', 'branch', 'restaurant')
            .prefetch_related('allowed_halls')
        )

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        branch = serializer.validated_data.get('branch') or get_request_branch(self.request, restaurant)
        serializer.save(restaurant=restaurant, branch=branch)
