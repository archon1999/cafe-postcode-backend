from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import PosSessionSerializer


class PosMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(PosSessionSerializer({'token': '', 'user': request.user}).data)
