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


class TvMonitorPairingClaimSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128)


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
