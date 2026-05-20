from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.restaurants.models import Restaurant


class LocalAgentAuthTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant', auth_code='123456')

    def test_restaurant_code_login_returns_agent_token(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/restaurant-code/',
            {'code': '123456', 'name': 'Cashier PC', 'version': '0.2.0'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['agentToken'].startswith('cpa_'))
        self.assertIn('/ws/local-agent/', response.data['wsUrl'])
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.name, 'Cashier PC')
        self.assertTrue(LocalAgent.authenticate_token(response.data['agentToken']))

    def test_restaurant_code_login_rejects_invalid_code(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/restaurant-code/',
            {'code': '999999'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LocalAgentCommandServiceTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant', auth_code='123456')
        self.agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')

    def test_execute_returns_offline_error_without_online_agent(self):
        with self.assertRaises(LocalAgentUnavailableError):
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='agent.health',
                payload={},
                timeout_seconds=1,
            )

    def test_execute_times_out_when_agent_does_not_return_result(self):
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        with self.assertRaises(LocalAgentCommandError) as context:
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='agent.health',
                payload={},
                timeout_seconds=1,
            )

        self.assertEqual(context.exception.code, 'LOCAL_AGENT_TIMEOUT')
        self.assertIn('before it was delivered', str(context.exception))
        self.assertEqual(context.exception.result['commandStatus'], LocalAgentCommand.Status.PENDING)
        command = LocalAgentCommand.objects.get(agent=self.agent)
        self.assertEqual(command.status, LocalAgentCommand.Status.TIMED_OUT)
        self.assertEqual(command.error['commandType'], 'agent.health')
