import json
import logging

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.services.tv_monitor_pairing import (
    TvMonitorPairingError,
    TvMonitorPairingExpired,
    TvMonitorPairingRequired,
    authenticate_tv_monitor_device,
    claim_tv_monitor_pairing,
    create_tv_monitor_pairing,
    get_tv_monitor_pairing,
)
from apps.platform.services import FeatureGateService
from apps.users.api.pos.serializers import PosRestaurantContextSerializer
from common.api.throttling import LoginRateThrottle
from common.api.scopes import get_request_restaurant

from .kitchen_monitor_queue import serialize_kitchen_monitor_queue


logger = logging.getLogger('apps.kitchen.tv_monitor_diagnostics')


class TvMonitorPairingClaimSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128)


class TvMonitorDiagnosticSerializer(serializers.Serializer):
    event = serializers.ChoiceField(
        choices=(
            'page_loaded',
            'queue_success',
            'queue_error',
            'render_error',
            'window_error',
            'unhandled_rejection',
            'announcement_play_started',
            'announcement_play_ended',
            'announcement_play_blocked',
            'announcement_play_error',
        )
    )
    message = serializers.CharField(required=False, allow_blank=True, max_length=1000, default='')
    client_time = serializers.DateTimeField(required=False, allow_null=True)
    context = serializers.JSONField(required=False, default=dict)

    def validate_context(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Context must be an object.')
        if len(json.dumps(value, default=str, ensure_ascii=False)) > 4096:
            raise serializers.ValidationError('Context is too large.')
        return value


class TvMonitorPairingCreateView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        pairing, poll_token, claim_token = create_tv_monitor_pairing()
        return Response(
            {
                'id': pairing.id,
                'poll_token': poll_token,
                'claim_token': claim_token,
                'expires_at': pairing.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class TvMonitorPairingStatusView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pairing_id):
        poll_token = request.headers.get('X-TV-Pairing-Token', '').strip()
        try:
            pairing = get_tv_monitor_pairing(pairing_id=pairing_id, poll_token=poll_token)
        except TvMonitorPairingExpired:
            return Response({'status': 'expired'}, status=status.HTTP_410_GONE)
        except TvMonitorPairingError:
            return Response({'detail': 'Pairing session is invalid.'}, status=status.HTTP_404_NOT_FOUND)

        if pairing.device_id is None:
            return Response({'status': 'pending', 'expires_at': pairing.expires_at})
        return Response(
            {
                'status': 'paired',
                'restaurant_context': PosRestaurantContextSerializer(pairing.device.restaurant).data,
            }
        )


class TvMonitorPairingClaimView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [LoginRateThrottle]

    def post(self, request, pairing_id):
        serializer = TvMonitorPairingClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            device = claim_tv_monitor_pairing(
                pairing_id=pairing_id,
                claim_token=serializer.validated_data['claim_token'],
                restaurant=get_request_restaurant(request),
            )
        except TvMonitorPairingExpired:
            return Response({'detail': 'Pairing session has expired.'}, status=status.HTTP_410_GONE)
        except TvMonitorPairingError as error:
            raise serializers.ValidationError({'detail': str(error)}) from error

        return Response({'status': 'paired', 'restaurant_name': device.restaurant.name})


class TvKitchenMonitorQueueView(APIView):
    permission_classes = [permissions.AllowAny]
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        token = request.headers.get('X-TV-Token', '').strip()
        try:
            device = authenticate_tv_monitor_device(token=token)
        except TvMonitorPairingRequired as error:
            return Response(
                {'code': 'tv_pairing_required', 'detail': str(error)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        self.feature_gate_service_class().ensure_kitchen_access(restaurant=device.restaurant)
        return Response(serialize_kitchen_monitor_queue(device.restaurant))


class TvMonitorDiagnosticView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = request.headers.get('X-TV-Token', '').strip()
        try:
            device = authenticate_tv_monitor_device(token=token)
        except TvMonitorPairingRequired as error:
            return Response(
                {'code': 'tv_pairing_required', 'detail': str(error)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = TvMonitorDiagnosticSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        log_payload = {
            'event': payload['event'],
            'message': payload['message'],
            'client_time': payload.get('client_time'),
            'context': payload['context'],
            'device_id': str(device.id),
            'restaurant_id': str(device.restaurant_id),
            'restaurant_name': device.restaurant.name,
            'remote_addr': (
                request.META.get('HTTP_CF_CONNECTING_IP')
                or request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR', '')
            ),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
        }
        logger.info('tv_monitor_diagnostic %s', json.dumps(log_payload, default=str, ensure_ascii=False, sort_keys=True))
        return Response(status=status.HTTP_204_NO_CONTENT)
