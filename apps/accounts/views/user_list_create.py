from rest_framework import generics, permissions

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class UserListCreateView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return (
            User.objects.filter(restaurant_profile__restaurant=restaurant)
            .select_related('role', 'restaurant_profile', 'restaurant_profile__primary_hall')
            .prefetch_related('restaurant_profile__allowed_halls')
        )

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
