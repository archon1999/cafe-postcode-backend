import logging

from django.db import connection, transaction
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.lan import private_lan_endpoints
from apps.local_agents.models import LocalAgent
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.restaurants.models import Restaurant
from apps.devices.authentication import authenticate_device_request
from apps.devices.models import Device, SecurityEvent
from apps.devices.migration_window import legacy_cohort_eligible, legacy_pos_migration_enabled, pos_device_proof_required
from apps.devices.security import record_security_event
from apps.users.models import AuthSession
from apps.users.api.pos.serializers import (
    PosLoginSerializer,
    LegacyRestaurantCodeSerializer,
    PosRestaurantContextSerializer,
    PosSessionSerializer,
    PosTransportDiscoverySerializer,
)
from apps.users.services import AuthSessionService
from common.api.permissions import EndpointRBACPermission
from common.api.client_ip import get_client_ip
from common.api.scopes import get_request_restaurant
from common.api.throttling import PinDeviceRateThrottle, PinLoginRateThrottle, RestaurantCodeMigrationRateThrottle

logger = logging.getLogger(__name__)


class LegacyRestaurantCodeView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RestaurantCodeMigrationRateThrottle]

    def post(self, request):
        if not legacy_pos_migration_enabled():
            return Response(
                {'code': 'restaurant_code_disabled', 'detail': 'Restaurant code migration is disabled.'},
                status=status.HTTP_410_GONE,
            )
        serializer = LegacyRestaurantCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        table = Restaurant._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT id FROM {connection.ops.quote_name(table)} WHERE auth_code = %s LIMIT 1',
                [serializer.validated_data['code']],
            )
            row = cursor.fetchone()
        restaurant = Restaurant.objects.filter(pk=row[0], is_active=True).first() if row else None
        if restaurant is None or not legacy_cohort_eligible(created_at=restaurant.created_at):
            return Response(
                {'code': 'restaurant_code_invalid', 'detail': 'Restaurant code is invalid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = dict(PosRestaurantContextSerializer(restaurant).data)
        payload['coordinator'] = _issue_coordinator(restaurant=restaurant)
        return Response(payload)


def _trusted_agent_context(agent, *, restaurant):
    device = getattr(agent, 'device', None)
    if (
        device is None
        or device.restaurant_id != restaurant.id
        or device.type != Device.Type.LOCAL_AGENT
        or not device.is_active
        or device.lease_expires_at <= timezone.now()
        or device.public_key_algorithm != Device.PublicKeyAlgorithm.ED25519
    ):
        return {}
    return {
        'agentDeviceId': str(device.id),
        'agentSigningPublicKeyAlgorithm': device.public_key_algorithm,
        'agentSigningPublicKey': device.public_key,
        'agentSigningPublicKeyFingerprint': device.public_key_fingerprint,
    }


def _issue_coordinator(*, restaurant, device=None, terminal_id='', terminal_name=''):
    agent = (
        LocalAgent.objects.select_related('device')
        .filter(restaurant=restaurant, is_active=True)
        .first()
    )
    if agent is None:
        return None
    trusted_agent = _trusted_agent_context(agent, restaurant=restaurant)
    if agent.device_id is not None and not trusted_agent:
        return None
    lan_endpoints = private_lan_endpoints(agent.lan_endpoints or [])
    # The common deployment runs the POS browser and Local Agent on the same
    # Windows terminal. Prefer loopback so VPN/hotspot adapters cannot make an
    # otherwise healthy Agent appear offline. Device proof and the encrypted
    # channel are still required by the Agent on this endpoint.
    coordinator_urls = ['http://127.0.0.1:18181', *lan_endpoints]
    coordinator = {
        'restaurantId': str(restaurant.id),
        'coordinatorUrls': list(dict.fromkeys(coordinator_urls)),
        **trusted_agent,
    }

    # A pre-rollout POS can still discover the existing coordinator during the
    # bounded migration window. Its already-stored legacy credential is never
    # returned by this endpoint. Fresh paired devices are provisioned directly
    # with their approved public key over the signed Agent command channel.
    if device is None:
        return coordinator
    if (
        device.restaurant_id != restaurant.id
        or device.type != Device.Type.POS_TERMINAL
        or not device.is_active
        or device.public_key_algorithm != Device.PublicKeyAlgorithm.P256_SHA256
        or not trusted_agent
    ):
        return None
    # Migrated legacy terminals retain their stable Edge terminal id. Fresh
    # QR-paired terminals use the backend device UUID so stale browser-local
    # terminal ids cannot collide with an older Agent binding.
    terminal_id = str((device.metadata or {}).get('terminalId') or device.id).strip()
    coordinator['terminalId'] = terminal_id
    try:
        result = LocalAgentCommandService().execute(
            restaurant=restaurant,
            command_type='edge.terminal.bind',
            payload={
                'terminalId': terminal_id,
                'terminalName': str(terminal_name or '').strip() or 'POS terminal',
                'deviceId': str(device.id),
                'publicKeyAlgorithm': device.public_key_algorithm,
                'publicKey': device.public_key,
                'publicKeyFingerprint': device.public_key_fingerprint,
            },
            timeout_seconds=2,
        )
        if (
            str(result.get('terminalId') or '') != terminal_id
            or str(result.get('deviceId') or '').lower() != str(device.id).lower()
            or str(result.get('restaurantId') or '').lower() != str(restaurant.id).lower()
        ):
            return None
        return coordinator
    except (LocalAgentUnavailableError, LocalAgentCommandError):
        return None


class PosTransportDiscoveryView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request):
        serializer = PosTransportDiscoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = get_request_restaurant(request)
        session = request.auth if isinstance(request.auth, AuthSession) else None
        device = session.device if session is not None else getattr(request, 'device', None)
        return Response(
            {
                'restaurantId': str(restaurant.id),
                'coordinator': _issue_coordinator(
                    restaurant=restaurant,
                    device=device,
                    terminal_id=serializer.validated_data.get('terminal_id', ''),
                    terminal_name=serializer.validated_data.get('terminal_name', ''),
                ),
            }
        )


class PosPinLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PinLoginRateThrottle, PinDeviceRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        device = None
        if pos_device_proof_required() or request.headers.get('X-Device-Id'):
            device = authenticate_device_request(request, expected_types=[Device.Type.POS_TERMINAL])
        serializer = PosLoginSerializer(
            data=request.data,
            context={'restaurant': device.restaurant if device is not None else None},
        )
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning('POS login failed', extra={'ui_channel': 'pos', 'client_ip': get_client_ip(request)})
            record_security_event(
                event_type='PIN_FAILED',
                severity=SecurityEvent.Severity.MEDIUM,
                request=request,
                restaurant=device.restaurant if device is not None else None,
                device=device,
                result='DENIED',
            )
            raise
        user = serializer.validated_data['user']
        restaurant = serializer.validated_data['restaurant']
        token, session = self.auth_session_service_class().issue(
            user=user,
            request=request,
            surface='pos',
            device=device,
            restaurant=restaurant,
        )
        record_security_event(
            event_type='POS_LOGIN_SUCCEEDED',
            severity=SecurityEvent.Severity.INFO,
            request=request,
            restaurant=restaurant,
            actor=user,
            device=device,
            auth_session=session,
            result='SUCCESS',
        )
        return Response(PosSessionSerializer({'token': token, 'user': user, 'session': session, 'restaurant': restaurant}).data)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        self.auth_session_service_class().revoke(request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PosMeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        return Response(PosSessionSerializer({'token': '', 'user': request.user}).data)


class PosLockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        session = request.auth if isinstance(request.auth, AuthSession) else None
        if session is None or session.surface != AuthSession.Surface.POS:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if session.locked_at is None:
            session.locked_at = timezone.now()
            session.save(update_fields=['locked_at', 'updated_at'])
        record_security_event(
            event_type='POS_SESSION_LOCKED',
            request=request,
            restaurant=session.restaurant,
            actor=request.user,
            device=session.device,
            auth_session=session,
            result='SUCCESS',
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PosUnlockSerializer(serializers.Serializer):
    pin = serializers.RegexField(r'^\d{4}$')

    def validate(self, attrs):
        user = self.context['user']
        if not user.is_active or not user.restaurant_access_active or not user.check_pin(attrs['pin']):
            raise ValidationError({'pin': 'Invalid PIN code.'})
        attrs['user'] = user
        attrs['restaurant'] = self.context['restaurant']
        return attrs


class PosUnlockView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [PinLoginRateThrottle, PinDeviceRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        session = request.auth if isinstance(request.auth, AuthSession) else None
        if session is None or session.surface != AuthSession.Surface.POS or session.locked_at is None:
            return Response(
                {'code': 'session_not_locked', 'detail': 'POS session is not locked.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = PosUnlockSerializer(
            data=request.data,
            context={'user': request.user, 'restaurant': session.restaurant},
        )
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            record_security_event(
                event_type='PIN_FAILED',
                severity=SecurityEvent.Severity.MEDIUM,
                request=request,
                restaurant=session.restaurant,
                actor=request.user,
                device=session.device,
                auth_session=session,
                result='DENIED',
                metadata={'flow': 'unlock'},
            )
            raise
        with transaction.atomic():
            session = AuthSession.objects.select_for_update().get(pk=session.pk)
            if session.status != AuthSession.Status.ACTIVE or session.locked_at is None:
                return Response(
                    {'code': 'session_not_locked', 'detail': 'POS session is not locked.'},
                    status=status.HTTP_409_CONFLICT,
                )
            token, new_session = self.auth_session_service_class().issue(
                user=request.user,
                request=request,
                surface=AuthSession.Surface.POS,
                device=session.device,
                restaurant=session.restaurant,
            )
            now = timezone.now()
            session.status = AuthSession.Status.REVOKED
            session.revoked_at = now
            session.save(update_fields=['status', 'revoked_at', 'updated_at'])
        record_security_event(
            event_type='POS_SESSION_UNLOCKED',
            request=request,
            restaurant=session.restaurant,
            actor=request.user,
            device=session.device,
            auth_session=new_session,
            result='SUCCESS',
        )
        return Response(
            PosSessionSerializer(
                {
                    'token': token,
                    'user': request.user,
                    'session': new_session,
                    'restaurant': session.restaurant,
                }
            ).data
        )

__all__ = [
    'LogoutView',
    'PosLockView',
    'PosMeView',
    'PosPinLoginView',
    'PosTransportDiscoveryView',
    'PosUnlockView',
]
