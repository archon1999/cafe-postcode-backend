import time
from urllib.parse import urlencode

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from apps.local_agents.models import LocalAgent, LocalAgentCommand


class LocalAgentUnavailableError(Exception):
    code = 'LOCAL_AGENT_OFFLINE'


class LocalAgentCommandError(Exception):
    def __init__(self, message: str, *, code: str = 'LOCAL_AGENT_ERROR', result: dict | None = None):
        super().__init__(message)
        self.code = code
        self.result = result or {}


def local_agent_group_name(agent_id) -> str:
    return f'local_agent_{agent_id}'


class LocalAgentCommandService:
    poll_interval_seconds = 0.2

    def _enqueue_command(self, *, restaurant, command_type: str, payload: dict, timeout_seconds: int):
        agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
        if agent is None or not agent.is_online():
            raise LocalAgentUnavailableError('Local agent is offline.')

        command = LocalAgentCommand.objects.create(
            agent=agent,
            command_type=command_type,
            payload=payload,
            timeout_seconds=max(int(timeout_seconds or 30), 1),
        )
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            local_agent_group_name(agent.id),
            {
                'type': 'agent.command',
                'command_id': str(command.id),
                'command_type': command_type,
                'payload': payload,
            },
        )
        return agent, command

    def enqueue(self, *, restaurant, command_type: str, payload: dict, timeout_seconds: int = 30) -> dict:
        _agent, command = self._enqueue_command(
            restaurant=restaurant,
            command_type=command_type,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return {
            'accepted': True,
            'commandId': str(command.id),
            'commandStatus': command.status,
        }

    def execute(self, *, restaurant, command_type: str, payload: dict, timeout_seconds: int = 30) -> dict:
        agent, command = self._enqueue_command(
            restaurant=restaurant,
            command_type=command_type,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

        deadline = time.monotonic() + command.timeout_seconds
        while time.monotonic() < deadline:
            command.refresh_from_db(fields=['status', 'result', 'error'])
            if command.status == LocalAgentCommand.Status.SUCCEEDED:
                return command.result or {}
            if command.status == LocalAgentCommand.Status.FAILED:
                error = command.error or {}
                raise LocalAgentCommandError(
                    str(error.get('message') or error.get('detail') or 'Local agent command failed.'),
                    code=str(error.get('code') or 'LOCAL_AGENT_ERROR'),
                    result=command.result or {},
                )
            time.sleep(self.poll_interval_seconds)

        command.refresh_from_db(fields=['status', 'sent_at', 'result', 'error'])
        timeout_detail = self._timeout_detail(command=command, agent=agent)
        command.status = LocalAgentCommand.Status.TIMED_OUT
        command.completed_at = timezone.now()
        command.error = {
            'code': 'LOCAL_AGENT_TIMEOUT',
            'message': timeout_detail['message'],
            **timeout_detail,
        }
        command.save(update_fields=['status', 'completed_at', 'error', 'updated_at'])
        raise LocalAgentCommandError(
            timeout_detail['message'],
            code='LOCAL_AGENT_TIMEOUT',
            result=timeout_detail,
        )

    def _timeout_detail(self, *, command, agent) -> dict:
        status = str(command.status or LocalAgentCommand.Status.PENDING)
        if status == LocalAgentCommand.Status.PENDING:
            message = (
                'Local agent command timed out before it was delivered. '
                'If web and websocket servers run as separate local processes, set REDIS_URL for a shared channel layer '
                'or run a single Daphne process.'
            )
        elif status == LocalAgentCommand.Status.SENT:
            message = (
                'Local agent command was delivered but the agent did not return a result before timeout. '
                'Check the local agent terminal log and the local device response.'
            )
        else:
            message = 'Local agent command timed out.'
        return {
            'message': message,
            'commandId': str(command.id),
            'commandType': command.command_type,
            'commandStatus': status,
            'timeoutSeconds': command.timeout_seconds,
            'sentAt': command.sent_at.isoformat() if command.sent_at else None,
            'agentId': str(agent.id),
            'agentLastSeenAt': agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        }

    def local_http_request(
        self,
        *,
        restaurant,
        method: str,
        url: str,
        query: dict | None = None,
        json_body: dict | None = None,
        form_body: dict | None = None,
        timeout_seconds: int = 30,
    ) -> dict:
        request_url = url
        if query:
            separator = '&' if '?' in request_url else '?'
            request_url = f'{request_url}{separator}{urlencode({key: value for key, value in query.items() if value not in (None, "")})}'
        return self.execute(
            restaurant=restaurant,
            command_type='local_http.request',
            payload={
                'method': method.upper(),
                'url': request_url,
                'json': json_body,
                'form': form_body,
                'timeoutSeconds': timeout_seconds,
            },
            timeout_seconds=timeout_seconds + 5,
        )

    def printer_raw(self, *, restaurant, payload: dict, timeout_seconds: int = 15) -> dict:
        return self.execute(
            restaurant=restaurant,
            command_type='printer.raw',
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
