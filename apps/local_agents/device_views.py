from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.crypto import pairing_key_proof_message, public_key_fingerprint, verify_signature
from apps.devices.models import Device, SecurityEvent
from apps.devices.migration_window import legacy_cohort_eligible, legacy_local_agent_migration_enabled
from apps.devices.security import record_security_event
from apps.devices.serializers import DeviceSerializer, KeyProofSerializer
from apps.devices.services import CAPABILITIES_BY_TYPE, DEVICE_LEASE_TTL
from apps.local_agents.models import LocalAgent
from common.api.throttling import DeviceMigrationRateThrottle


class LocalAgentDeviceMigrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='Local Agent')
    platform = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    app_version = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    public_key_algorithm = serializers.ChoiceField(choices=Device.PublicKeyAlgorithm.choices)
    public_key = serializers.CharField(max_length=2048)
    key_proof = KeyProofSerializer()


class LocalAgentDeviceMigrationView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [DeviceMigrationRateThrottle]

    @transaction.atomic
    def post(self, request):
        if not legacy_local_agent_migration_enabled():
            return Response(
                {'code': 'legacy_migration_disabled', 'detail': 'Local Agent migration is disabled.'},
                status=status.HTTP_410_GONE,
            )
        authorization = str(request.headers.get('Authorization') or '')
        scheme, _, raw_token = authorization.partition(' ')
        # A migrated credential is accepted only here so a client can safely
        # retry after losing the successful migration response. Every normal
        # Local Agent auth path rejects it immediately after device binding.
        agent = (
            LocalAgent.authenticate_token(raw_token.strip(), allow_migrated=True)
            if scheme.lower() == 'bearer'
            else None
        )
        if agent is None:
            return Response(
                {'code': 'legacy_agent_credential_invalid', 'detail': 'Legacy Local Agent credential is invalid.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        agent = (
            LocalAgent.objects.select_for_update(of=('self',))
            .select_related('restaurant', 'device')
            .get(pk=agent.pk)
        )
        if not legacy_cohort_eligible(created_at=agent.created_at):
            return Response(
                {'code': 'legacy_migration_disabled', 'detail': 'Local Agent is not part of the legacy cohort.'},
                status=status.HTTP_410_GONE,
            )
        serializer = LocalAgentDeviceMigrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fingerprint = public_key_fingerprint(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
        )
        proof = data['key_proof']
        if not verify_signature(
            algorithm=data['public_key_algorithm'],
            public_key=data['public_key'],
            signature=proof['signature'],
            message=pairing_key_proof_message(nonce=proof['nonce'], fingerprint=fingerprint),
        ):
            return Response(
                {'code': 'device_proof_invalid', 'detail': 'Device key proof is invalid.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if agent.device_id is not None:
            if agent.device.public_key_fingerprint != fingerprint or not agent.device.is_active:
                return Response(
                    {'code': 'agent_already_migrated', 'detail': 'Local Agent is already bound to another device.'},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response({'device': DeviceSerializer(agent.device).data})
        now = timezone.now()
        try:
            device = Device.objects.create(
                restaurant=agent.restaurant,
                type=Device.Type.LOCAL_AGENT,
                name=data['name'] or agent.name or 'Local Agent',
                platform=data['platform'],
                app_version=data['app_version'] or agent.version,
                public_key_algorithm=data['public_key_algorithm'],
                public_key=data['public_key'],
                public_key_fingerprint=fingerprint,
                capabilities=CAPABILITIES_BY_TYPE[Device.Type.LOCAL_AGENT],
                metadata={'migration': 'legacy-cpa', 'legacyAgentId': str(agent.pk)},
                paired_at=now,
                lease_expires_at=now + DEVICE_LEASE_TTL,
                last_seen_at=now,
            )
        except IntegrityError:
            return Response(
                {'code': 'device_already_registered', 'detail': 'Device key or Local Agent slot is already registered.'},
                status=status.HTTP_409_CONFLICT,
            )
        agent.device = device
        agent.credential_migrated_at = now
        agent.save(update_fields=['device', 'credential_migrated_at', 'updated_at'])
        record_security_event(
            event_type='LEGACY_LOCAL_AGENT_MIGRATED',
            severity=SecurityEvent.Severity.MEDIUM,
            request=request,
            restaurant=agent.restaurant,
            device=device,
            result='SUCCESS',
            metadata={'legacyAgentId': str(agent.pk)},
        )
        ws_url = request.build_absolute_uri('/ws/local-agent/')
        ws_url = ws_url.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        return Response({'device': DeviceSerializer(device).data, 'wsUrl': ws_url}, status=status.HTTP_201_CREATED)
