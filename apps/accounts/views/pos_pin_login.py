import logging

from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.services import AuthSessionService
from apps.accounts.serializers import PosLoginSerializer, PosSessionSerializer
from common.api.throttling import PinLoginRateThrottle

logger = logging.getLogger(__name__)


class PosPinLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PinLoginRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        serializer = PosLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning('POS login failed', extra={'ui_channel': 'pos', 'client_ip': request.META.get('REMOTE_ADDR')})
            raise
        user = serializer.validated_data['user']
        restaurant = serializer.validated_data['restaurant']
        token, session = self.auth_session_service_class().issue(user=user, ui_channel='pos', request=request)
        return Response(PosSessionSerializer({'token': token.key, 'user': user, 'session': session, 'restaurant': restaurant}).data)
