from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.authentication import authenticate_local_agent
from apps.users.models import User
from apps.workforce.models import AttendancePunch, GeofenceConfig
from apps.workforce.services import create_device_punch
from common.api.throttling import LocalAgentRateThrottle


class DevicePunchSerializer(serializers.Serializer):
    terminal_id = serializers.RegexField(r'^[A-Za-z0-9._:-]{1,63}$')
    source_event_id = serializers.RegexField(r'^[A-Za-z0-9._:-]{1,64}$')
    employee_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=AttendancePunch.Type.choices)
    device_recorded_at = serializers.DateTimeField()

    def validate_device_recorded_at(self, value):
        now = timezone.now()
        if value < now - timedelta(days=90) or value > now + timedelta(hours=24):
            raise serializers.ValidationError('Device event must be within the 90-day backfill window.')
        return value


class DevicePunchBatchSerializer(serializers.Serializer):
    device_clock_at_poll = serializers.DateTimeField(required=False)
    events = DevicePunchSerializer(many=True, allow_empty=False, max_length=100)


class HikvisionPunchImportView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]
    max_body_bytes = 128 * 1024

    def post(self, request):
        raw_body = getattr(getattr(request, '_request', request), 'body', b'') or b''
        if len(raw_body) > self.max_body_bytes:
            return Response({'detail': 'Attendance batch is too large.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if not request.headers.get('X-Device-Id'):
            return Response({'code': 'device_required', 'detail': 'Paired Local Agent proof is required.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        agent = authenticate_local_agent(request)
        if agent is None or agent.device_id is None:
            return Response({'code': 'device_required', 'detail': 'Paired Local Agent proof is required.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        if not GeofenceConfig.objects.filter(restaurant=agent.restaurant, workforce_enabled=True).exists():
            return Response({'code': 'workforce_disabled', 'detail': 'Workforce pilot is disabled for this branch.'},
                            status=status.HTTP_403_FORBIDDEN)
        serializer = DevicePunchBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        events = serializer.validated_data['events']
        employee_ids = {event['employee_id'] for event in events}
        employees = {
            user.pk: user for user in User.objects.filter(
                pk__in=employee_ids, is_active=True,
                restaurant_profile__restaurant=agent.restaurant,
                employee_profile__employment_status='active',
            )
        }
        if len(employees) != len(employee_ids):
            raise serializers.ValidationError({'events': 'An employee does not belong to this branch.'})
        results = []
        with transaction.atomic():
            for event in events:
                punch, duplicate = create_device_punch(
                    restaurant=agent.restaurant,
                    employee=employees[event['employee_id']],
                    source_event_id=f"{event['terminal_id']}:{event['source_event_id']}",
                    event_type=event['type'],
                    device_recorded_at=event['device_recorded_at'],
                    device_clock_at_poll=serializer.validated_data.get('device_clock_at_poll'),
                )
                results.append({
                    'source_event_id': event['source_event_id'],
                    'terminal_id': event['terminal_id'],
                    'punch_id': punch.pk,
                    'duplicate': duplicate,
                    'clock_skew_seconds': punch.clock_skew_seconds,
                    'requires_review': punch.requires_review,
                })
        return Response({'results': results})
