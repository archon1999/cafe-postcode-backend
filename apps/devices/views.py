from datetime import datetime, timezone as datetime_timezone

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics, permissions, serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView
import qrcode

from apps.devices.authentication import (
    DeviceLeaseRecoveryAuthentication,
    authenticate_device_request,
    pairing_nonce_available,
)
from apps.devices.crypto import (
    pairing_key_proof_message,
    pos_migration_attestation_message,
    public_key_fingerprint,
    sha256_hex,
    verify_signature,
)
from apps.devices.models import Device, DevicePairing, SecurityEvent
from apps.devices.migration_window import legacy_cohort_eligible, legacy_pos_migration_enabled, legacy_tv_migration_enabled
from apps.devices.permissions import CanViewSecurityEvents, IsSuperuser
from common.api.admin_permissions import RecentAdminMFAPermission
from apps.devices.security import record_security_event
from apps.devices.serializers import (
    DevicePairingAdminSerializer,
    DevicePairingCreateSerializer,
    DevicePairingStatusSerializer,
    DeviceRevokeSerializer,
    DeviceSerializer,
    KeyProofSerializer,
    PairingDecisionSerializer,
    PairingRejectSerializer,
    SecurityEventSerializer,
)
from apps.devices.services import (
    CAPABILITIES_BY_TYPE,
    DEVICE_LEASE_TTL,
    DeviceLeaseExpired,
    DevicePairingConflict,
    DevicePairingError,
    DevicePairingExpired,
    approve_pairing,
    create_pairing,
    get_pairing_status,
    reject_pairing,
    renew_device_lease,
    revoke_device,
)
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.restaurants.models import Restaurant
from apps.users.api.pos.serializers import PosRestaurantContextSerializer
from apps.users.models import AuthSession
from common.api.throttling import DeviceMigrationRateThrottle, DevicePairingRateThrottle


def _pairing_error_response(error):
    if isinstance(error, DeviceLeaseExpired):
        http_status = status.HTTP_401_UNAUTHORIZED
    elif isinstance(error, DevicePairingExpired):
        http_status = status.HTTP_410_GONE
    elif isinstance(error, DevicePairingConflict):
        http_status = status.HTTP_409_CONFLICT
    else:
        http_status = status.HTTP_400_BAD_REQUEST
    return Response({'code': error.code, 'detail': str(error)}, status=http_status)


def _device_payload(device):
    return DeviceSerializer(device).data


def _query_value(request, *names):
    for name in names:
        value = request.query_params.get(name)
        if value is not None:
            return str(value).strip()
    return ''


def _pairing_qr_payload(claim_url):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(claim_url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    path = ''.join(
        f'M{column} {row}h1v1h-1z'
        for row, modules in enumerate(matrix)
        for column, enabled in enumerate(modules)
        if enabled
    )
    return {'qrPath': path, 'qrSize': len(matrix)}


class DevicePairingCreateView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DevicePairingRateThrottle]

    def post(self, request):
        serializer = DevicePairingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        key_proof = payload.pop('key_proof')
        try:
            pairing, poll_token, claim_token, claim_url = create_pairing(
                **payload,
                proof_nonce=key_proof['nonce'],
                proof_signature=key_proof['signature'],
            )
        except DevicePairingError as error:
            return _pairing_error_response(error)
        return Response(
            {
                'id': pairing.id,
                'pollToken': poll_token,
                'claimToken': claim_token,
                'claimUrl': claim_url,
                'displayCode': pairing.display_code,
                'expiresAt': pairing.expires_at,
                'status': 'pending',
                **_pairing_qr_payload(claim_url),
            },
            status=status.HTTP_201_CREATED,
        )


class DevicePairingStatusView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, pairing_id):
        serializer = DevicePairingStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pairing = get_pairing_status(
                pairing_id=pairing_id,
                replay_guard=pairing_nonce_available,
                **serializer.validated_data,
            )
        except DevicePairingError as error:
            return _pairing_error_response(error)

        if pairing.status == DevicePairing.Status.PENDING:
            return Response({'status': 'pending', 'expiresAt': pairing.expires_at})
        if pairing.status == DevicePairing.Status.REJECTED:
            return Response({'status': 'rejected'})
        device = pairing.device
        return Response(
            {
                'status': 'paired',
                'device': _device_payload(device),
                'restaurantContext': (
                    PosRestaurantContextSerializer(device.restaurant).data if device.restaurant_id else None
                ),
            }
        )


class DeviceMeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        device = authenticate_device_request(request)
        return Response(
            {
                'device': _device_payload(device),
                'restaurantContext': (
                    PosRestaurantContextSerializer(device.restaurant).data if device.restaurant_id else None
                ),
            }
        )


class DeviceLeaseRenewView(APIView):
    # A POS client normally carries its session token on every request.  The
    # default session authentication would validate the bound device before
    # this view can deliberately recover an expired lease.  Keep this endpoint
    # independent of session authentication and authenticate the signed device
    # proof exactly once below.
    authentication_classes = [DeviceLeaseRecoveryAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Pairing is permanent until an administrator revokes the device.  The
        # rolling lease gates ordinary privileged traffic, but possession of
        # the registered private key is sufficient to recover an ACTIVE
        # device after it has been offline for longer than one lease period.
        device = request.auth
        try:
            device = renew_device_lease(device=device, request=request)
        except DeviceLeaseExpired as error:
            return _pairing_error_response(error)
        return Response({'device': _device_payload(device), 'leaseExpiresAt': device.lease_expires_at})


class LegacyPosMigrationAttestationSerializer(serializers.Serializer):
    version = serializers.ChoiceField(choices=('v1',))
    restaurant_id = serializers.UUIDField()
    local_agent_device_id = serializers.UUIDField()
    terminal_id = serializers.CharField(min_length=8, max_length=128)
    public_key_fingerprint = serializers.RegexField(r'^[0-9a-f]{64}$')
    issued_at = serializers.IntegerField(min_value=1)
    expires_at = serializers.IntegerField(min_value=1)
    nonce = serializers.RegexField(r'^[A-Za-z0-9_-]{22,128}$')
    signature = serializers.RegexField(r'^[A-Za-z0-9_-]{40,512}$')


class LegacyPosMigrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    platform = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    app_version = serializers.CharField(max_length=50, allow_blank=True, required=False, default='')
    public_key_algorithm = serializers.ChoiceField(choices=Device.PublicKeyAlgorithm.choices)
    public_key = serializers.CharField(max_length=2048)
    key_proof = KeyProofSerializer()
    agent_attestation = LegacyPosMigrationAttestationSerializer()


class LegacyPosMigrationView(APIView):
    # This endpoint is intentionally independent of a legacy 24-hour POS
    # session. Authority comes from the existing per-terminal Edge credential,
    # attested by an already paired Local Agent, plus proof of the new key.
    # It is exposed only during the bounded production migration window.
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DeviceMigrationRateThrottle]
    command_service_class = LocalAgentCommandService

    def _bind_terminal(self, *, request, restaurant, agent_device, device, terminal_id):
        try:
            result = self.command_service_class().execute(
                restaurant=restaurant,
                command_type='edge.terminal.bind',
                payload={
                    'terminalId': terminal_id,
                    'terminalName': device.name,
                    'deviceId': str(device.pk),
                    'publicKeyAlgorithm': device.public_key_algorithm,
                    'publicKey': device.public_key,
                    'publicKeyFingerprint': device.public_key_fingerprint,
                },
                timeout_seconds=2,
            )
        except LocalAgentUnavailableError:
            reason = 'agent_unavailable'
            response_status = status.HTTP_503_SERVICE_UNAVAILABLE
            response_code = 'local_agent_unavailable'
            response_detail = 'Local Agent is unavailable; terminal migration was not completed.'
        except LocalAgentCommandError:
            reason = 'command_failed'
            response_status = status.HTTP_502_BAD_GATEWAY
            response_code = 'terminal_bind_failed'
            response_detail = 'Local Agent did not accept the terminal binding.'
        else:
            valid_ack = (
                isinstance(result, dict)
                and str(result.get('terminalId') or '') == terminal_id
                and str(result.get('deviceId') or '').lower() == str(device.pk).lower()
                and str(result.get('restaurantId') or '').lower() == str(restaurant.pk).lower()
            )
            if valid_ack:
                return None
            reason = 'ack_mismatch'
            response_status = status.HTTP_502_BAD_GATEWAY
            response_code = 'terminal_bind_failed'
            response_detail = 'Local Agent did not confirm the terminal binding.'

        record_security_event(
            event_type='LEGACY_POS_TERMINAL_BIND_FAILED',
            severity=SecurityEvent.Severity.HIGH,
            request=request,
            restaurant=restaurant,
            device=device,
            result='DENIED',
            metadata={'agentDeviceId': str(agent_device.pk), 'reason': reason},
        )
        return Response(
            {'code': response_code, 'detail': response_detail},
            status=response_status,
        )

    def post(self, request):
        if not legacy_pos_migration_enabled():
            return Response(
                {'code': 'legacy_migration_disabled', 'detail': 'Legacy POS migration is disabled.'},
                status=status.HTTP_410_GONE,
            )
        serializer = LegacyPosMigrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attestation = data['agent_attestation']
        fingerprint = public_key_fingerprint(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
        )
        key_proof = data['key_proof']
        if not verify_signature(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
            signature=key_proof['signature'],
            message=pairing_key_proof_message(nonce=key_proof['nonce'], fingerprint=fingerprint),
        ):
            return Response(
                {'code': 'device_proof_invalid', 'detail': 'Device key proof is invalid.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        response_status = status.HTTP_200_OK
        with transaction.atomic():
            now_timestamp = int(timezone.now().timestamp())
            if (
                attestation['public_key_fingerprint'] != fingerprint
                or attestation['expires_at'] <= now_timestamp
                or attestation['issued_at'] > now_timestamp + 30
                or attestation['expires_at'] - attestation['issued_at'] > 300
            ):
                return Response(
                    {'code': 'migration_attestation_invalid', 'detail': 'Migration attestation is invalid.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            agent_device = Device.objects.select_for_update(of=('self',)).select_related(
                'restaurant',
                'local_agent_record',
            ).filter(
                pk=attestation['local_agent_device_id'],
                type=Device.Type.LOCAL_AGENT,
                status=Device.Status.ACTIVE,
                revoked_at__isnull=True,
                lease_expires_at__gt=timezone.now(),
            ).first()
            if (
                agent_device is None
                or agent_device.restaurant_id != attestation['restaurant_id']
                or not agent_device.restaurant.is_active
                or not legacy_cohort_eligible(
                    created_at=getattr(getattr(agent_device, 'local_agent_record', None), 'created_at', None)
                )
                or not verify_signature(
                    algorithm=agent_device.public_key_algorithm,
                    public_key=agent_device.public_key,
                    signature=attestation['signature'],
                    message=pos_migration_attestation_message(attestation),
                )
            ):
                return Response(
                    {'code': 'migration_attestation_invalid', 'detail': 'Migration attestation is invalid.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            restaurant = agent_device.restaurant
            legacy_migration_key = sha256_hex(
                f'{str(agent_device.pk).lower()}\n{attestation["terminal_id"]}'
            )
            device = Device.objects.select_for_update(of=('self',)).filter(
                legacy_migration_key=legacy_migration_key,
            ).first()
            if device is not None:
                if device.public_key_fingerprint != fingerprint or not device.is_active:
                    record_security_event(
                        event_type='LEGACY_POS_TERMINAL_CONFLICT',
                        severity=SecurityEvent.Severity.HIGH,
                        request=request,
                        restaurant=restaurant,
                        device=agent_device,
                        result='DENIED',
                        metadata={'terminalMigrationKey': legacy_migration_key},
                    )
                    return Response(
                        {'code': 'terminal_already_migrated', 'detail': 'This legacy terminal is already migrated.'},
                        status=status.HTTP_409_CONFLICT,
                    )
            else:
                replay_key = f'pos-migration:{agent_device.pk}:{sha256_hex(attestation["nonce"])}'
                if not cache.add(replay_key, '1', timeout=600):
                    record_security_event(
                        event_type='PAIRING_REPLAY_DETECTED',
                        severity=SecurityEvent.Severity.HIGH,
                        request=request,
                        restaurant=restaurant,
                        device=agent_device,
                        result='DENIED',
                        metadata={'flow': 'legacy_pos_migration'},
                    )
                    return Response(
                        {'code': 'device_replay_detected', 'detail': 'Migration attestation was already used.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                try:
                    # Keep the uniqueness failure inside a savepoint so the outer
                    # request transaction remains usable for the idempotency lookup.
                    with transaction.atomic():
                        device = Device.objects.create(
                            restaurant=restaurant,
                            type=Device.Type.POS_TERMINAL,
                            name=data['name'],
                            platform=data['platform'],
                            app_version=data['app_version'],
                            public_key_algorithm=data['public_key_algorithm'],
                            public_key=data['public_key'],
                            public_key_fingerprint=fingerprint,
                            capabilities=CAPABILITIES_BY_TYPE[Device.Type.POS_TERMINAL],
                            metadata={
                                'terminalId': attestation['terminal_id'],
                                'agentDeviceId': str(agent_device.pk),
                                'migration': 'legacy-agent-attested',
                            },
                            legacy_migration_key=legacy_migration_key,
                            paired_at=timezone.now(),
                            lease_expires_at=timezone.now() + DEVICE_LEASE_TTL,
                            last_seen_at=timezone.now(),
                        )
                except IntegrityError:
                    device = Device.objects.filter(legacy_migration_key=legacy_migration_key).first()
                    if device is None or device.public_key_fingerprint != fingerprint or not device.is_active:
                        return Response(
                            {
                                'code': 'device_already_registered',
                                'detail': 'This device key or terminal is already registered.',
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                else:
                    response_status = status.HTTP_201_CREATED
                    record_security_event(
                        event_type='LEGACY_POS_DEVICE_MIGRATED',
                        severity=SecurityEvent.Severity.MEDIUM,
                        request=request,
                        restaurant=restaurant,
                        device=device,
                        result='SUCCESS',
                        metadata={'agentDeviceId': str(agent_device.pk)},
                    )

        bind_error = self._bind_terminal(
            request=request,
            restaurant=restaurant,
            agent_device=agent_device,
            device=device,
            terminal_id=attestation['terminal_id'],
        )
        if bind_error is not None:
            return bind_error
        return Response(
            {
                'device': _device_payload(device),
                'restaurantContext': PosRestaurantContextSerializer(restaurant).data,
            },
            status=response_status,
        )


class LegacyTvMigrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='Kitchen TV')
    platform = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    app_version = serializers.CharField(max_length=50, allow_blank=True, required=False, default='')
    public_key_algorithm = serializers.ChoiceField(choices=Device.PublicKeyAlgorithm.choices)
    public_key = serializers.CharField(max_length=2048)
    key_proof = KeyProofSerializer()


class LegacyTvMigrationView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DeviceMigrationRateThrottle]

    @transaction.atomic
    def post(self, request):
        if not legacy_tv_migration_enabled():
            return Response(
                {'code': 'legacy_migration_disabled', 'detail': 'Legacy TV migration is disabled.'},
                status=status.HTTP_410_GONE,
            )
        from apps.kitchen.models import TvMonitorDevice
        from apps.kitchen.services.tv_monitor_pairing import (
            TvMonitorPairingRequired,
            authenticate_tv_monitor_device,
        )

        raw_token = str(request.headers.get('X-TV-Token') or '').strip()
        try:
            legacy_device = authenticate_tv_monitor_device(token=raw_token, allow_migrated=True)
        except TvMonitorPairingRequired:
            return Response(
                {'code': 'legacy_tv_credential_invalid', 'detail': 'Legacy TV credential is invalid.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        legacy_device = TvMonitorDevice.objects.select_for_update(of=('self',)).select_related(
            'restaurant',
            'device',
        ).get(pk=legacy_device.pk)
        serializer = LegacyTvMigrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fingerprint = public_key_fingerprint(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
        )
        key_proof = data['key_proof']
        if not verify_signature(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
            signature=key_proof['signature'],
            message=pairing_key_proof_message(nonce=key_proof['nonce'], fingerprint=fingerprint),
        ):
            return Response(
                {'code': 'device_proof_invalid', 'detail': 'Device key proof is invalid.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if legacy_device.device_id is not None:
            existing = legacy_device.device
            if existing.public_key_fingerprint == fingerprint and existing.is_active:
                return Response(
                    {
                        'device': _device_payload(existing),
                        'restaurantContext': PosRestaurantContextSerializer(existing.restaurant).data,
                    }
                )
            return Response(
                {'code': 'tv_already_migrated', 'detail': 'This legacy TV is already bound to another device.'},
                status=status.HTTP_409_CONFLICT,
            )
        replay_key = f'tv-migration:{legacy_device.pk}:{sha256_hex(key_proof["nonce"])}'
        if not cache.add(replay_key, '1', timeout=600):
            return Response(
                {'code': 'device_replay_detected', 'detail': 'Migration key proof was already used.'},
                status=status.HTTP_409_CONFLICT,
            )
        now = timezone.now()
        migration_key = sha256_hex(f'legacy-tv\n{legacy_device.pk}')
        try:
            with transaction.atomic():
                device = Device.objects.create(
                    restaurant=legacy_device.restaurant,
                    type=Device.Type.TV_MONITOR,
                    name=data['name'] or 'Kitchen TV',
                    platform=data['platform'],
                    app_version=data['app_version'],
                    public_key_algorithm=data['public_key_algorithm'],
                    public_key=data['public_key'],
                    public_key_fingerprint=fingerprint,
                    capabilities=CAPABILITIES_BY_TYPE[Device.Type.TV_MONITOR],
                    metadata={'migration': 'legacy-tv', 'legacyTvDeviceId': str(legacy_device.pk)},
                    legacy_migration_key=migration_key,
                    paired_at=now,
                    lease_expires_at=now + DEVICE_LEASE_TTL,
                    last_seen_at=now,
                )
        except IntegrityError:
            return Response(
                {'code': 'device_already_registered', 'detail': 'This TV device key is already registered.'},
                status=status.HTTP_409_CONFLICT,
            )
        legacy_device.device = device
        legacy_device.credential_migrated_at = now
        legacy_device.save(update_fields=['device', 'credential_migrated_at', 'updated_at'])
        record_security_event(
            event_type='LEGACY_TV_DEVICE_MIGRATED',
            severity=SecurityEvent.Severity.MEDIUM,
            request=request,
            restaurant=legacy_device.restaurant,
            device=device,
            result='SUCCESS',
            metadata={'legacyTvDeviceId': str(legacy_device.pk)},
        )
        return Response(
            {
                'device': _device_payload(device),
                'restaurantContext': PosRestaurantContextSerializer(legacy_device.restaurant).data,
            },
            status=status.HTTP_201_CREATED,
        )


class DeviceListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]
    serializer_class = DeviceSerializer

    def get_queryset(self):
        queryset = Device.objects.select_related('restaurant').all()
        restaurant_id = _query_value(self.request, 'restaurant_id', 'restaurantId')
        device_type = _query_value(self.request, 'device_type', 'deviceType')
        status_filter = _query_value(self.request, 'status')
        search = _query_value(self.request, 'search')
        ordering = _query_value(self.request, 'ordering')
        if restaurant_id:
            queryset = queryset.filter(restaurant_id=restaurant_id)
        if device_type:
            queryset = queryset.filter(type=device_type)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(restaurant__name__icontains=search)
                | Q(public_key_fingerprint__icontains=search)
            )
        ordering_map = {
            'restaurantName': 'restaurant__name',
            'name': 'name',
            'type': 'type',
            'status': 'status',
            'lastSeenAt': 'last_seen_at',
            'pairedAt': 'paired_at',
        }
        descending = ordering.startswith('-')
        key = ordering[1:] if descending else ordering
        field = ordering_map.get(key, 'restaurant__name')
        return queryset.order_by(f'-{field}' if descending else field, 'name')


class DeviceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, pk):
        device = get_object_or_404(Device.objects.select_related('restaurant'), pk=pk)
        return Response({'device': _device_payload(device)})


class DeviceRevokeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser, RecentAdminMFAPermission]

    def post(self, request, pk):
        device = get_object_or_404(Device.objects.select_related('restaurant'), pk=pk)
        serializer = DeviceRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = revoke_device(
            device=device,
            revoked_by=request.user,
            reason=serializer.validated_data['reason'],
            request=request,
        )
        return Response({'device': _device_payload(device)})


class DevicePairingAdminListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]
    serializer_class = DevicePairingAdminSerializer

    def get_queryset(self):
        queryset = DevicePairing.objects.select_related('device__restaurant').all()
        status_filter = _query_value(self.request, 'status')
        device_type = _query_value(self.request, 'device_type', 'deviceType')
        search = _query_value(self.request, 'search')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if device_type:
            queryset = queryset.filter(device_type=device_type)
        if search:
            queryset = queryset.filter(
                Q(requested_name__icontains=search) | Q(public_key_fingerprint__icontains=search)
            )
        return queryset


class DevicePairingApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser, RecentAdminMFAPermission]

    def post(self, request, pairing_id):
        serializer = PairingDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            device = approve_pairing(
                pairing_id=pairing_id,
                approved_by=request.user,
                request=request,
                **serializer.validated_data,
            )
        except DevicePairingError as error:
            return _pairing_error_response(error)
        return Response({'status': 'paired', 'device': _device_payload(device)})


class DevicePairingRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser, RecentAdminMFAPermission]

    def post(self, request, pairing_id):
        serializer = PairingRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pairing = reject_pairing(
                pairing_id=pairing_id,
                rejected_by=request.user,
                request=request,
                **serializer.validated_data,
            )
        except DevicePairingError as error:
            return _pairing_error_response(error)
        return Response({'status': 'rejected', 'pairing': DevicePairingAdminSerializer(pairing).data})


class DeviceMigrationSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request):
        from apps.local_agents.models import LocalAgent
        from apps.local_agents.rollout import legacy_pos_bridge_summary
        from apps.kitchen.models import TvMonitorDevice

        restaurants = list(
            Restaurant.objects.filter(is_active=True)
            .select_related('local_agent', 'local_agent__device')
            .annotate(
                active_pos_devices=Count(
                    'devices',
                    filter=Q(devices__type=Device.Type.POS_TERMINAL, devices__status=Device.Status.ACTIVE),
                    distinct=True,
                ),
                unbound_pos_sessions=Count(
                    'auth_sessions',
                    filter=Q(
                        auth_sessions__surface=AuthSession.Surface.POS,
                        auth_sessions__status=AuthSession.Status.ACTIVE,
                        auth_sessions__device__isnull=True,
                    ),
                    distinct=True,
                ),
            )
            .order_by('name', 'id')
        )
        restaurant_total = len(restaurants)
        with_agent = Device.objects.filter(
            restaurant__is_active=True,
            type=Device.Type.LOCAL_AGENT,
            status=Device.Status.ACTIVE,
        ).values('restaurant_id').distinct().count()
        by_type = {
            row['type']: row['count']
            for row in Device.objects.filter(status=Device.Status.ACTIVE).values('type').annotate(count=Count('id'))
        }
        branches = []
        for restaurant in restaurants:
            try:
                agent = restaurant.local_agent
            except LocalAgent.DoesNotExist:
                agent = None
            agent_device = agent.device if agent is not None else None
            branches.append(
                {
                    'restaurantId': str(restaurant.id),
                    'restaurantName': restaurant.name,
                    'activePOSDevices': restaurant.active_pos_devices,
                    'unboundPOSSessions': restaurant.unbound_pos_sessions,
                    'agent': None
                    if agent is None
                    else {
                        'id': str(agent.id),
                        'version': agent.version,
                        'lastSeenAt': agent.last_seen_at.isoformat() if agent.last_seen_at else None,
                        'online': agent.is_online(),
                        'protocolVersion': agent.protocol_version,
                        'deviceMigrated': agent_device is not None,
                        'deviceStatus': agent_device.status if agent_device is not None else None,
                        'bridge': legacy_pos_bridge_summary(agent),
                    },
                }
            )
        return Response(
            {
                'restaurants': {
                    'total': restaurant_total,
                    'withActiveAgentDevice': with_agent,
                    'withoutActiveAgentDevice': max(0, restaurant_total - with_agent),
                },
                'devices': {
                    'active': Device.objects.filter(status=Device.Status.ACTIVE).count(),
                    'revoked': Device.objects.filter(status=Device.Status.REVOKED).count(),
                    'byType': by_type,
                },
                'pairings': {
                    'pending': DevicePairing.objects.filter(
                        status=DevicePairing.Status.PENDING,
                        expires_at__gt=timezone.now(),
                    ).count(),
                },
                'legacy': {
                    'localAgentsTotal': LocalAgent.objects.filter(is_active=True).count(),
                    'localAgentsMigrated': LocalAgent.objects.filter(device__isnull=False).count(),
                    'posSessionsUnbound': AuthSession.objects.filter(
                        surface=AuthSession.Surface.POS,
                        status=AuthSession.Status.ACTIVE,
                        device__isnull=True,
                    ).count(),
                    'tvMonitorsTotal': TvMonitorDevice.objects.filter(revoked_at__isnull=True).count(),
                    'tvMonitorsMigrated': TvMonitorDevice.objects.filter(
                        revoked_at__isnull=True,
                        device__isnull=False,
                    ).count(),
                },
                # Per-branch coverage is operational rollout evidence only. It
                # never grants access and is always scoped by the authenticated
                # Agent row rather than a client-supplied restaurant identifier.
                'branches': branches,
            }
        )


class SecurityEventListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, CanViewSecurityEvents]
    serializer_class = SecurityEventSerializer

    def get_queryset(self):
        queryset = SecurityEvent.objects.select_related('restaurant', 'actor', 'device', 'acknowledged_by')
        if self.request.user.is_superuser:
            restaurant_id = _query_value(self.request, 'restaurant_id', 'restaurantId')
            if restaurant_id:
                queryset = queryset.filter(restaurant_id=restaurant_id)
        else:
            queryset = queryset.filter(restaurant=self.request.user.get_restaurant_scope())
        filters = {
            'event_type': 'event_type',
            'severity': 'severity',
            'device_id': 'device_id',
            'result': 'result',
        }
        for field, query_name in filters.items():
            value = _query_value(self.request, query_name)
            if value:
                queryset = queryset.filter(**{field: value})
        acknowledged = str(self.request.query_params.get('acknowledged') or '').strip().lower()
        if acknowledged in {'true', 'false'}:
            queryset = queryset.filter(acknowledged_at__isnull=acknowledged == 'false')
        start = parse_datetime(str(self.request.query_params.get('from') or ''))
        end = parse_datetime(str(self.request.query_params.get('to') or ''))
        if start:
            if timezone.is_naive(start):
                start = timezone.make_aware(start, datetime_timezone.utc)
            queryset = queryset.filter(created_at__gte=start)
        if end:
            if timezone.is_naive(end):
                end = timezone.make_aware(end, datetime_timezone.utc)
            queryset = queryset.filter(created_at__lte=end)
        search = str(self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(event_type__icontains=search)
                | Q(restaurant__name__icontains=search)
                | Q(actor__full_name__icontains=search)
                | Q(request_id__icontains=search)
            )
        return queryset


class SecurityEventAcknowledgeView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanViewSecurityEvents]

    def post(self, request, pk):
        queryset = SecurityEvent.objects.select_related('restaurant', 'actor', 'device', 'acknowledged_by')
        if not request.user.is_superuser:
            queryset = queryset.filter(restaurant=request.user.get_restaurant_scope())
        event = get_object_or_404(queryset, pk=pk)
        if event.acknowledged_at is None:
            event.acknowledged_at = timezone.now()
            event.acknowledged_by = request.user
            event.save(update_fields=['acknowledged_at', 'acknowledged_by', 'updated_at'])
        return Response({'event': SecurityEventSerializer(event).data})
