from rest_framework import generics, permissions

from apps.accounts.models import Role
from apps.accounts.serializers import RoleSerializer
from common.api.permissions import HasPermissionCode


class RoleListView(generics.ListAPIView):
    queryset = Role.objects.prefetch_related('permissions').all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'users.manage'
