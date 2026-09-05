import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APIRequestFactory
from apps.billing.models import Payment
from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User, AdminRefreshFamily
from apps.users.services.auth_sessions import AuthSessionService


class AdminFinancialFlowTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username='finance-admin', password='test-only')
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.agent.capabilities = ['financial_events_v2']
        self.agent.save(update_fields=['capabilities'])
        now = timezone.now()
        family = AdminRefreshFamily.objects.create(user=self.admin, absolute_expires_at=now+timedelta(hours=1), last_activity_at=now, mfa_verified_at=now)
        token, _ = AuthSessionService().issue(user=self.admin, request=APIRequestFactory().get('/api/v1/admin/auth/me/'), surface='admin', refresh_family=family, mfa_verified_at=now)
        self.client.force_authenticate(user=None)
        self.authorization = 'Token '+token
        self.client.credentials(HTTP_AUTHORIZATION=self.authorization, HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.pk))

    def command(self, actor=None):
        operation='admin:'+str(uuid.uuid4())
        LocalAgentCommand.objects.create(agent=self.agent, command_type='financial.execute', financial_operation_id=operation,
            payload={'userId':str(self.user.pk), 'actorUserId':str(actor or self.admin.pk)}, status='succeeded',
            result={'responseStatus':200, 'response':{'receipt':{'id':'original-receipt'}}})
        return operation

    def test_real_admin_session_uses_admin_status_surface(self):
        operation = self.command()
        response = self.client.get(f'/api/v1/admin/billing/financial-commands/{operation}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['response']['receipt']['id'], 'original-receipt')
        self.assertEqual(self.client.get(f'/api/v1/pos/financial-commands/{operation}/').status_code, 401)

    def test_admin_lookup_requires_original_actor_and_selected_restaurant(self):
        operation = self.command(actor=uuid.uuid4())
        self.assertEqual(self.client.get(f'/api/v1/admin/billing/financial-commands/{operation}/').status_code, 404)
        own = self.command()
        other = Restaurant.objects.create(name='Other branch')
        self.client.credentials(HTTP_AUTHORIZATION=self.authorization, HTTP_X_ADMIN_RESTAURANT_ID=str(other.pk))
        response = self.client.get(f'/api/v1/admin/billing/financial-commands/{own}/')
        self.assertEqual(response.status_code, 404)
        self.client.credentials(HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(self.client.get(f'/api/v1/admin/billing/financial-commands/{own}/').status_code, 400)

    @patch('apps.local_agents.services.LocalAgentCommandService.execute')
    def test_admin_dispatch_preserves_original_cashier_and_records_actor(self, execute):
        order = Order.objects.create(restaurant=self.restaurant, opened_by=self.user, distribution_point=self.takeaway_distribution, channel='takeaway', order_number=910)
        payment = Payment.objects.create(order=order, cash_desk=self.cash_desk, received_by=self.user, amount=30000, method='cash', status='succeeded')
        execute.return_value = {'responseStatus':200, 'response':{'receipt':{'id':'original'}}}
        response = self.client.post(f'/api/v1/admin/billing/payments/{payment.pk}/retry-fiscal/', {}, format='json', HTTP_X_EDGE_OPERATION_ID='admin:test')
        self.assertEqual(response.status_code, 200, response.data)
        payload = execute.call_args.kwargs['payload']
        self.assertEqual(payload['userId'], str(self.user.pk))
        self.assertEqual(payload['actorUserId'], str(self.admin.pk))
        self.assertEqual(payload['path'], f'/api/v1/pos/billing/payments/{payment.pk}/retry-fiscal/')
        self.assertIsNone(self.admin.get_restaurant_scope())
