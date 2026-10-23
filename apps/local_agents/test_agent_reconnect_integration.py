"""Opt-in real HTTP contract with the Go Agent and disposable Django test DB.

CAFE_RUN_AGENT_INTEGRATION=1 python manage.py test apps.local_agents.test_agent_reconnect_integration
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless

from cryptography.hazmat.primitives import serialization
from django.test import LiveServerTestCase, override_settings

from apps.billing.models import Payment, Receipt
from apps.local_agents.models import LocalAgent, LocalAgentCommand, LocalAgentMutationInbox
from apps.local_agents.tests_support import AgentTestIdentity
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosTestCase


@skipUnless(os.environ.get('CAFE_RUN_AGENT_INTEGRATION') == '1', 'Opt-in cross-repository local integration')
@override_settings(ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class AgentReconnectIntegrationTests(LiveServerTestCase):
    host = '127.0.0.1'

    def test_offline_sale_restart_lost_ack_reconnect_and_canonical_refresh(self):
        # Reuse the isolated fixture builder, never a user's development database.
        class Fixtures(PosTestCase):
            permission_codes = (*PosTestCase.permission_codes, 'pos_fiscal_receipts.skip')
        Fixtures.setUpTestData()
        Fixtures.restaurant.service_fee_enabled = False
        Fixtures.restaurant.save()
        Fixtures.create_cash_shift()
        agent, _ = LocalAgent.issue_for_restaurant(restaurant=Fixtures.restaurant)
        identity = AgentTestIdentity(agent)
        private = identity.private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        repository = Path(__file__).resolve().parents[2]
        fixture = {'backend': self.live_server_url, 'restaurant': str(Fixtures.restaurant.pk),
                   'user': str(Fixtures.user.pk), 'table': str(Fixtures.table.pk), 'item': str(Fixtures.catalog_item.pk),
                   'device': str(identity.device.pk), 'seed': base64.urlsafe_b64encode(private).decode().rstrip('='),
                   'permissions': list(Fixtures.permission_codes)}
        with tempfile.TemporaryDirectory(prefix='postcode-local-contract-') as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(fixture), encoding='utf-8')
            env = {**os.environ, 'CAFE_LOCAL_CONTRACT_FIXTURE': str(path)}
            result = subprocess.run(['go', 'test', './cmd/local-agent', '-run', '^TestLocalBackendReconnectContract$', '-count=1', '-v'],
                                    cwd=repository.parent / 'local-agent', env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
        self.assertEqual(Order.objects.filter(restaurant=Fixtures.restaurant, status='closed').count(), 1)
        payment = Payment.objects.get(order__restaurant=Fixtures.restaurant)
        self.assertEqual(payment.amount, 30000)
        self.assertEqual(payment.order.closed_at, payment.occurred_at)
        self.assertEqual(Receipt.objects.filter(order__restaurant=Fixtures.restaurant).count(), 1)
        self.assertEqual(LocalAgentCommand.objects.count(), 0)
        self.assertFalse(LocalAgentMutationInbox.objects.filter(restaurant=Fixtures.restaurant).exclude(state='applied').exists())
