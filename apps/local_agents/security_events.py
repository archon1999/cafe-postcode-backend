import re
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.models import SecurityEvent
from apps.devices.security import sanitize_security_metadata
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.models import LocalAgent


LOCAL_EVENT_SEVERITIES = {
    'LOCAL_AGENT_AUTH_DENIED': SecurityEvent.Severity.HIGH,
    'LOCAL_AUTH_THROTTLED': SecurityEvent.Severity.HIGH,
    'LOCAL_DEVICE_PROOF_DENIED': SecurityEvent.Severity.HIGH,
    'LOCAL_LEGACY_POS_BRIDGE_DENIED': SecurityEvent.Severity.HIGH,
    'LOCAL_NETWORK_DENIED': SecurityEvent.Severity.HIGH,
    'LOCAL_ORIGIN_DENIED': SecurityEvent.Severity.MEDIUM,
    'LOCAL_PIN_FAILED': SecurityEvent.Severity.MEDIUM,
    'LOCAL_RBAC_DENIED': SecurityEvent.Severity.MEDIUM,
    'LOCAL_SCOPE_DENIED': SecurityEvent.Severity.MEDIUM,
    'LOCAL_SECURE_CHANNEL_DENIED': SecurityEvent.Severity.HIGH,
    'LOCAL_SESSION_DENIED': SecurityEvent.Severity.LOW,
}
LOCAL_EVENT_BATCH_MAX_BODY = 128 * 1024
LOCAL_EVENT_BATCHES_PER_MINUTE = 10
TRANSIENT_SECURE_CHANNEL_REASON = 'secure_channel_invalid'


def _is_single_stale_secure_channel(event) -> bool:
    """Ignore the expected first request made with a pre-restart channel.

    Local Agent channel sessions intentionally live only in process memory.  A
    valid, device-signed POS request can therefore present one stale channel ID
    immediately after an Agent update or restart.  The POS renews the channel
    and retries automatically, so treating that first request as a HIGH device
    proof denial creates a false security incident.  Repeated failures remain
    auditable because their coalesced count is greater than one.
    """
    return (
        event['event_type'] == 'LOCAL_DEVICE_PROOF_DENIED'
        and event['reason'] == TRANSIENT_SECURE_CHANNEL_REASON
        and event['count'] == 1
    )


def _event_severity(event):
    if (
        event['event_type'] == 'LOCAL_DEVICE_PROOF_DENIED'
        and event['reason'] == TRANSIENT_SECURE_CHANNEL_REASON
    ):
        return SecurityEvent.Severity.MEDIUM
    return LOCAL_EVENT_SEVERITIES[event['event_type']]


def _batch_rate_allowed(device_id) -> bool:
    bucket = int(timezone.now().timestamp()) // 60
    key = f'local-agent-security-events:{device_id}:{bucket}'
    if cache.add(key, 1, timeout=120):
        return True
    try:
        return cache.incr(key) <= LOCAL_EVENT_BATCHES_PER_MINUTE
    except ValueError:
        return False


class LocalSecurityEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_type = serializers.ChoiceField(choices=tuple(LOCAL_EVENT_SEVERITIES))
    terminal_id = serializers.RegexField(re.compile(r'^[A-Za-z0-9._:-]{1,128}$'), required=False, allow_blank=True)
    source_hash = serializers.RegexField(re.compile(r'^[0-9a-f]{64}$'))
    reason = serializers.RegexField(re.compile(r'^[a-z0-9][a-z0-9_.-]{0,79}$'))
    count = serializers.IntegerField(min_value=1, max_value=1_000_000)
    occurred_at = serializers.DateTimeField()

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError('Security event contains unsupported fields.')
        return super().to_internal_value(data)

    def validate_occurred_at(self, value):
        now = timezone.now()
        if value < now - timedelta(days=90) or value > now + timedelta(minutes=5):
            raise serializers.ValidationError('Event timestamp is outside the accepted window.')
        return value


class LocalSecurityEventBatchSerializer(serializers.Serializer):
    events = LocalSecurityEventSerializer(many=True, allow_empty=False, max_length=100)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {'events'}:
            raise serializers.ValidationError('Only an events batch is accepted.')
        return super().to_internal_value(data)


class LocalAgentSecurityEventBatchView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # This ingestion surface is intentionally device-proof only. The
        # temporary legacy cpa bearer migration cannot upload audit events.
        try:
            content_length = int(request.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            content_length = LOCAL_EVENT_BATCH_MAX_BODY + 1
        if content_length < 0 or content_length > LOCAL_EVENT_BATCH_MAX_BODY:
            return Response(
                {'detail': 'Security event batch is too large.'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        if not request.headers.get('X-Device-Id'):
            return Response(
                {'detail': 'A paired Local Agent device proof is required.', 'code': 'device_required'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        agent = authenticate_local_agent(request)
        if agent is None or agent.device_id is None:
            return Response(
                {'detail': 'A paired Local Agent device proof is required.', 'code': 'device_required'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        raw_body = getattr(getattr(request, '_request', request), 'body', b'') or b''
        if len(raw_body) > LOCAL_EVENT_BATCH_MAX_BODY:
            return Response(
                {'detail': 'Security event batch is too large.'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        if not _batch_rate_allowed(agent.device_id):
            return Response(
                {'detail': 'Too many security event batches.', 'code': 'security_event_throttled'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={'Retry-After': '60'},
            )
        serializer = LocalSecurityEventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        accepted_ids = []
        with transaction.atomic():
            # Serialize retries from one Agent before the exists/create pair;
            # request_id is indexed but intentionally shared with other event
            # producers and therefore cannot be globally unique.
            LocalAgent.objects.select_for_update().only('id').get(pk=agent.pk)
            for event in serializer.validated_data['events']:
                event_id = str(event['id'])
                request_id = f'la:{agent.device_id}:{event_id}'
                if _is_single_stale_secure_channel(event):
                    accepted_ids.append(event_id)
                    continue
                if not SecurityEvent.objects.filter(request_id=request_id).exists():
                    SecurityEvent.objects.create(
                        event_type=event['event_type'],
                        severity=_event_severity(event),
                        restaurant=agent.restaurant,
                        device=agent.device,
                        request_id=request_id,
                        result='DENIED',
                        metadata=sanitize_security_metadata(
                            {
                                'sourceHash': event['source_hash'],
                                'terminalId': event.get('terminal_id', ''),
                                'reason': event['reason'],
                                'count': event['count'],
                                'occurredAt': event['occurred_at'].isoformat(),
                                'localAgentEventId': event_id,
                            }
                        ),
                    )
                accepted_ids.append(event_id)
        return Response({'acceptedIds': accepted_ids}, status=status.HTTP_202_ACCEPTED)
