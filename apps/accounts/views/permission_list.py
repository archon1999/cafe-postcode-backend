from rest_framework import generics, permissions

from apps.accounts.models import Permission
from apps.accounts.serializers import PermissionSerializer
from common.api.permissions import EndpointRBACPermission


class PermissionListView(generics.ListAPIView):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
