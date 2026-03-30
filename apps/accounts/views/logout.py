from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.services import AuthSessionService


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        self.auth_session_service_class().revoke(request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
