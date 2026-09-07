import hashlib
import json
from pathlib import Path
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api.permissions import IsAdmin
from common.api.admin_permissions import RecentAdminMFAPermission
from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.services import local_agent_group_name


SUPPORT_CAPABILITY = 'support_commands_v1'
CATALOG = json.loads(Path(__file__).with_name('support_catalog.json').read_text(encoding='utf-8-sig'))
COMMANDS = {item['name']: item for item in CATALOG}


def validate_command(name, parameters):
    definition = COMMANDS.get(name)
    if definition is None:
        raise ValidationError({'name': 'Unsupported Agent command.'})
    if definition.get('localOnly'):
        raise ValidationError({'name': 'This command is available only in the local Agent CLI.'})
    if not isinstance(parameters, dict):
        raise ValidationError({'parameters': 'An object is required.'})
    fields = {field['name']: field for field in definition['parameters']}
    if parameters.keys() - fields.keys():
        raise ValidationError({'parameters': 'Unknown command parameter.'})
    result = {}
    for key, field in fields.items():
        value = parameters.get(key, '')
        if not isinstance(value, str):
            raise ValidationError({'parameters': f'{key} must be text.'})
        value = value.strip()
        if (field['required'] and not value) or len(value) > field['maxLength']:
            raise ValidationError({'parameters': f'{key} is required or too long.'})
        if field.get('options') and value not in field['options']:
            raise ValidationError({'parameters': f'{key} is not an allowed value.'})
        result[key] = value
    return definition, result


def command_payload(command):
    result = command.result or {}
    status = result.get('status') if command.status in {LocalAgentCommand.Status.SUCCEEDED, LocalAgentCommand.Status.SENT} else command.status
    return {
        'requestId': str(command.pk), 'name': (command.payload or {}).get('name', ''),
        'parameters': (command.payload or {}).get('parameters', {}),
        'status': status or command.status, 'transportStatus': command.status,
        'result': result.get('result') or {}, 'error': result.get('error') or command.error or '',
        'createdAt': command.created_at, 'completedAt': None if status == 'running' else command.completed_at,
        'requestedBy': str(command.requested_by_id) if command.requested_by_id else None,
    }


def send_support_command(command):
    async_to_sync(get_channel_layer().group_send)(local_agent_group_name(command.agent_id), {
        'type': 'agent.command', 'command_id': str(command.pk),
        'command_type': command.command_type, 'payload': command.payload,
    })


class SupportCommandCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        return Response({'catalogVersion': 1, 'capability': SUPPORT_CAPABILITY,
                         'commands': [item for item in CATALOG if not item.get('localOnly')]})


class SupportCommandView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    parser_classes = [JSONParser]

    def get(self, request, pk, request_id=None):
        get_object_or_404(LocalAgent, pk=pk)
        queryset = LocalAgentCommand.objects.filter(agent_id=pk, command_type='support.execute')
        if request_id is not None:
            return Response(command_payload(get_object_or_404(queryset, pk=request_id)))
        return Response({'commands': [command_payload(item) for item in queryset.order_by('-created_at')[:100]]})

    def post(self, request, pk):
        if not isinstance(request.data, dict) or request.data.keys() - {'requestId', 'name', 'parameters'}:
            raise ValidationError('Unknown command fields.')
        name = request.data.get('name')
        if not isinstance(name, str):
            raise ValidationError({'name': 'Command name is required.'})
        definition, parameters = validate_command(name, request.data.get('parameters', {}))
        if definition['mutating'] and not RecentAdminMFAPermission().has_permission(request, self):
            self.permission_denied(request, message=RecentAdminMFAPermission.message)
        try:
            request_id = UUID(str(request.data.get('requestId', '')))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError({'requestId': 'A stable UUID is required.'}) from error
        agent = get_object_or_404(LocalAgent, pk=pk, is_active=True)
        payload = {'requestId': str(request_id), 'name': name, 'parameters': parameters}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        existing = LocalAgentCommand.objects.filter(pk=request_id).first()
        if existing is None and (not agent.is_online() or SUPPORT_CAPABILITY not in (agent.capabilities or [])):
            return Response({'code': 'AGENT_COMMANDS_UNAVAILABLE', 'detail': 'An online Agent 2.0.0 with command support is required.'}, status=409)
        with transaction.atomic():
            command, created = LocalAgentCommand.objects.get_or_create(pk=request_id, defaults={
                'agent': agent, 'command_type': 'support.execute', 'payload': payload,
                'payload_hash': digest, 'requested_by': request.user,
                'timeout_seconds': definition['timeoutSeconds'] + 10,
            })
            if command.agent_id != agent.pk or command.command_type != 'support.execute' or command.payload_hash != digest or command.requested_by_id != request.user.pk:
                return Response({'code': 'SUPPORT_REQUEST_CONFLICT', 'detail': 'Request ID belongs to another command.'}, status=409)
            should_send = agent.is_online() and (created or command.status in {
                LocalAgentCommand.Status.PENDING, LocalAgentCommand.Status.SENT, LocalAgentCommand.Status.TIMED_OUT,
            } or (command.status == LocalAgentCommand.Status.SUCCEEDED and (command.result or {}).get('status') == 'running'))
        if should_send:
            try:
                send_support_command(command)
            except Exception:
                # Persisted command is recoverable after reconnect; do not create a replacement ID.
                LocalAgentCommand.objects.filter(pk=command.pk).update(
                    error={'code': 'DELIVERY_PENDING', 'detail': 'Waiting for the Agent connection.'}, updated_at=timezone.now())
                command.refresh_from_db()
        return Response(command_payload(command), status=202 if should_send else 200)
