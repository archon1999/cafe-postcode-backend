from rest_framework import generics, permissions

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class UserRetrieveUpdateView(generics.RetrieveUpdateAPIView):
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
