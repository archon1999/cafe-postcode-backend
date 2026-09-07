import uuid
from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.support_commands import CATALOG, validate_command
from apps.local_agents.consumers import LocalAgentConsumer
from apps.restaurants.models import Restaurant
from apps.users.models import User


@override_settings(ADMIN_MFA_REQUIRED=False)
class SupportCommandTests(APITransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='support-admin', password='test-password')
        self.client.force_authenticate(self.admin)
        self.restaurant = Restaurant.objects.create(name='Support test')
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, version='2.0.0')
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.capabilities = ['support_commands_v1']
        self.agent.save()
        self.url = f'/api/v1/admin/local-agents/{self.agent.pk}/commands/'
        self.payload = {'requestId': str(uuid.uuid4()), 'name': 'sync.retry',
            'parameters': {'operationId': 'original-operation', 'reason': 'Retry after backend repair'}}

    @patch('apps.local_agents.support_commands.send_support_command')
    def test_async_command_retains_identity_actor_and_camel_parameters(self, send):
        first = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(first.status_code, 202, first.data)
        command = LocalAgentCommand.objects.get(pk=self.payload['requestId'])
        self.assertEqual(command.requested_by, self.admin)
        self.assertEqual(command.payload['parameters']['operationId'], 'original-operation')
        retry = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(retry.status_code, 202, retry.data)
        self.assertEqual(LocalAgentCommand.objects.count(), 1)
        self.assertEqual(send.call_count, 2)
        changed = {**self.payload, 'parameters': {**self.payload['parameters'], 'operationId': 'different'}}
        self.assertEqual(self.client.post(self.url, changed, format='json').status_code, 409)
        command.status = LocalAgentCommand.Status.SUCCEEDED
        command.result = {'status': 'unknown', 'error': 'Agent restarted before the result was saved.'}
        command.save()
        status = self.client.get(self.url + self.payload['requestId'] + '/')
        self.assertEqual(status.data['status'], 'unknown')
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 200)
        self.assertEqual(send.call_count, 2)

    @patch('apps.local_agents.support_commands.send_support_command')
    def test_offline_unsupported_arbitrary_fields_and_services_are_rejected(self, send):
        for patch_data in [
            {'name': 'shell.execute'},
            {'name': 'pairing.reset', 'parameters': {'reason': 'remote reset is forbidden'}},
            {'name': 'services.restart', 'parameters': {'service': 'WinDefend'}},
            {'parameters': {**self.payload['parameters'], 'sql': 'delete from edge_outbox'}},
            {'requestId': '../escape'},
        ]:
            response = self.client.post(self.url, {**self.payload, **patch_data}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.agent.status = LocalAgent.Status.OFFLINE
        self.agent.save()
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 409)
        self.assertFalse(LocalAgentCommand.objects.exists())
        send.assert_not_called()

    @override_settings(ADMIN_MFA_REQUIRED=True)
    @patch('apps.local_agents.support_commands.send_support_command')
    def test_mutations_require_recent_admin_mfa_and_read_commands_do_not(self, send):
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 403)
        inspect = {**self.payload, 'name': 'sync.inspect', 'parameters': {}}
        self.assertEqual(self.client.post(self.url, inspect, format='json').status_code, 202)
        self.assertEqual(send.call_count, 1)

    def test_fleet_commands_are_superuser_only(self):
        self.admin.is_superuser = False
        self.admin.save()
        self.assertEqual(self.client.get('/api/v1/admin/local-agents/commands/catalog/').status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 403)

    def test_catalog_has_unique_bounded_commands_and_no_shell_or_sql(self):
        self.assertEqual(len({item['name'] for item in CATALOG}), len(CATALOG))
        for item in CATALOG:
            parameters = {field['name']: (field.get('options') or ['value'])[0] for field in item['parameters']}
            if item.get('localOnly'):
                with self.assertRaises(ValidationError):
                    validate_command(item['name'], parameters)
                continue
            definition, _ = validate_command(item['name'], parameters)
            self.assertLessEqual(definition['timeoutSeconds'], 60)
            self.assertFalse({'shell', 'sql', 'path', 'url'} & parameters.keys())

    def test_restart_running_result_is_redelivered_and_terminal_outcome_is_monotonic(self):
        command = LocalAgentCommand.objects.create(agent=self.agent, command_type='support.execute',
            payload={'name': 'runtime.restart'}, status='sent', sent_at=timezone.now())
        consumer = LocalAgentConsumer()
        consumer.agent = self.agent
        result = {'requestId': str(command.pk), 'name': 'runtime.restart', 'status': 'running',
                  'result': {'restartRequested': True}}
        store = async_to_sync(consumer._store_command_result)
        pending = async_to_sync(consumer._pending_support_commands)
        store({'commandId': str(command.pk), 'ok': True, 'result': result})
        command.refresh_from_db()
        self.assertEqual(command.status, 'sent')
        self.assertIsNone(command.completed_at)
        self.assertEqual(self.client.get(self.url + str(command.pk) + '/').data['status'], 'running')
        self.assertEqual(pending(force=False), [])
        self.assertEqual(len(pending()), 1)  # Reconnect need not wait for the heartbeat cooldown.
        LocalAgentCommand.objects.filter(pk=command.pk).update(sent_at=timezone.now() - timedelta(seconds=31))
        self.assertEqual(len(pending(force=False)), 1)
        finished = {**result, 'status': 'succeeded', 'result': {'restartVerified': True, 'currentPid': 42}}
        store({'commandId': str(command.pk), 'ok': True, 'result': finished})
        store({'commandId': str(command.pk), 'ok': True, 'result': result})
        store({'commandId': str(command.pk), 'ok': False, 'error': {'detail': 'stale failure'}})
        command.refresh_from_db()
        self.assertEqual(command.result, finished)
        self.assertIsNotNone(command.completed_at)
        self.assertEqual(pending(), [])

    def test_old_running_transport_success_recovers_and_wrong_identity_is_ignored(self):
        command = LocalAgentCommand.objects.create(agent=self.agent, command_type='support.execute',
            payload={'name': 'runtime.restart'}, status='succeeded', result={'status': 'running'})
        consumer = LocalAgentConsumer()
        consumer.agent = self.agent
        self.assertEqual(len(async_to_sync(consumer._pending_support_commands)()), 1)
        store = async_to_sync(consumer._store_command_result)
        result = {'requestId': str(uuid.uuid4()), 'name': 'runtime.restart', 'status': 'succeeded'}
        store({'commandId': str(command.pk), 'ok': True, 'result': result})
        command.refresh_from_db()
        self.assertEqual(command.result, {'status': 'running'})
        result['requestId'] = str(command.pk)
        store({'commandId': str(command.pk), 'ok': True, 'result': result})
        self.assertEqual(async_to_sync(consumer._pending_support_commands)(), [])
