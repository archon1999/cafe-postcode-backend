from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import PosSessionSerializer
from common.api.permissions import EndpointRBACPermission


class PosMeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        return Response(PosSessionSerializer({'token': '', 'user': request.user}).data)
