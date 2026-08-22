from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.devices.migration_window import legacy_pos_migration_enabled
from apps.devices.models import Device, DevicePairing, SecurityEvent
from apps.local_agents.models import LocalAgent
from apps.platform.models import BusinessPartner
from apps.restaurants.models import Restaurant
from apps.telegram_reports.models import TelegramAccount, TelegramBranchSubscription
from apps.users.models import AuthSession, Role, User


class MonitoringOverviewApiTests(APITestCase):
    endpoint = '/api/v1/admin/monitoring/overview/'

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='monitoring-superuser',
            password='Strong-Monitoring-Password-123!',
        )
        cls.product_owner = User.objects.create_user(
            username='monitoring-product-owner',
            password='Strong-Monitoring-Password-123!',
            role=Role.objects.get(code='product_owner'),
            is_active=True,
            is_staff=True,
        )
        cls.regular_user = User.objects.create_user(
            username='monitoring-regular-user',
            password='Strong-Monitoring-Password-123!',
        )

    @staticmethod
    def create_device(*, restaurant, index, device_type, device_status=Device.Status.ACTIVE, last_seen_at=None):
        now = timezone.now()
        return Device.objects.create(
            restaurant=restaurant,
            type=device_type,
            name=f'Monitoring device {index}',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key=f'public-key-{index}',
            public_key_fingerprint=f'{index:064x}',
            status=device_status,
            paired_at=now,
            lease_expires_at=now + timedelta(days=30),
            last_seen_at=last_seen_at,
            revoked_at=now if device_status == Device.Status.REVOKED else None,
        )

    def test_overview_returns_branch_device_agent_and_security_aggregates(self):
        now = timezone.now()
        alpha = Restaurant.objects.create(name='Alpha branch')
        beta = Restaurant.objects.create(name='Beta branch')
        delta = Restaurant.objects.create(name='Delta branch')
        Restaurant.objects.create(name='Gamma branch')
        inactive = Restaurant.objects.create(name='Inactive branch', is_active=False)

        alpha_agent_device = self.create_device(
            restaurant=alpha,
            index=1,
            device_type=Device.Type.LOCAL_AGENT,
            last_seen_at=now - timedelta(seconds=5),
        )
        alpha_agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=alpha,
            name='Alpha agent',
            version='1.1.0',
        )
        alpha_agent.device = alpha_agent_device
        alpha_agent.status = LocalAgent.Status.ONLINE
        alpha_agent.last_seen_at = now
        alpha_agent.protocol_version = 3
        alpha_agent.capabilities = ['local_http', 'printer']
        alpha_agent.save()

        beta_agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=beta,
            name='Beta agent',
            version='1.0.4',
        )
        beta_agent.status = LocalAgent.Status.ONLINE
        beta_agent.last_seen_at = now - timedelta(minutes=5)
        beta_agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        delta_agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=delta,
            name='Inactive Delta agent',
            version='   ',
        )
        delta_agent.is_active = False
        delta_agent.status = LocalAgent.Status.ONLINE
        delta_agent.last_seen_at = now
        delta_agent.save(update_fields=['is_active', 'status', 'last_seen_at', 'updated_at'])

        alpha_pos = self.create_device(
            restaurant=alpha,
            index=2,
            device_type=Device.Type.POS_TERMINAL,
            last_seen_at=now - timedelta(seconds=2),
        )
        self.create_device(
            restaurant=alpha,
            index=3,
            device_type=Device.Type.TV_MONITOR,
            last_seen_at=now - timedelta(seconds=10),
        )
        self.create_device(
            restaurant=alpha,
            index=4,
            device_type=Device.Type.CONTROL_DEVICE,
            device_status=Device.Status.REVOKED,
            # A newer revoked heartbeat must not hide active-fleet freshness.
            last_seen_at=now + timedelta(seconds=1),
        )
        self.create_device(
            restaurant=beta,
            index=5,
            device_type=Device.Type.CONTROL_DEVICE,
            last_seen_at=now - timedelta(minutes=2),
        )
        self.create_device(
            restaurant=inactive,
            index=6,
            device_type=Device.Type.POS_TERMINAL,
            last_seen_at=now,
        )

        alpha_telegram_account = TelegramAccount.objects.create(
            telegram_user_id=101,
            chat_id=1001,
            notifications_enabled=False,
        )
        second_alpha_telegram_account = TelegramAccount.objects.create(
            telegram_user_id=102,
            chat_id=1002,
        )
        beta_telegram_account = TelegramAccount.objects.create(
            telegram_user_id=103,
            chat_id=1003,
        )
        TelegramBranchSubscription.objects.create(
            account=alpha_telegram_account,
            restaurant=alpha,
        )
        TelegramBranchSubscription.objects.create(
            account=second_alpha_telegram_account,
            restaurant=alpha,
        )
        TelegramBranchSubscription.objects.create(
            account=beta_telegram_account,
            restaurant=beta,
        )

        SecurityEvent.objects.create(
            event_type='ALPHA_HIGH',
            severity=SecurityEvent.Severity.HIGH,
            restaurant=alpha,
            device=alpha_pos,
        )
        SecurityEvent.objects.create(
            event_type='ALPHA_ACKNOWLEDGED_CRITICAL',
            severity=SecurityEvent.Severity.CRITICAL,
            restaurant=alpha,
            acknowledged_at=now,
            acknowledged_by=self.superuser,
        )
        SecurityEvent.objects.create(
            event_type='BETA_CRITICAL',
            severity=SecurityEvent.Severity.CRITICAL,
            restaurant=beta,
        )
        SecurityEvent.objects.create(
            event_type='PLATFORM_HIGH',
            severity=SecurityEvent.Severity.HIGH,
        )

        DevicePairing.objects.create(
            device_type=Device.Type.POS_TERMINAL,
            requested_name='Pending POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key='pending-key',
            public_key_fingerprint='a' * 64,
            poll_token_hash='b' * 64,
            claim_token_hash='c' * 64,
            display_code='123456',
            expires_at=now + timedelta(minutes=5),
        )
        DevicePairing.objects.create(
            device_type=Device.Type.POS_TERMINAL,
            requested_name='Expired POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key='expired-key',
            public_key_fingerprint='d' * 64,
            poll_token_hash='e' * 64,
            claim_token_hash='f' * 64,
            display_code='654321',
            expires_at=now - timedelta(seconds=1),
        )

        self.client.force_authenticate(self.product_owner)
        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNotNone(response.data['generatedAt'])
        self.assertEqual(
            response.data['summary'],
            {
                'totalBranches': 4,
                'agentOnline': 1,
                'agentOffline': 1,
                'agentMissing': 2,
                'activeDevices': 4,
                'revokedDevices': 1,
                'activePOSTerminals': 1,
                'pendingPairings': 1,
                'unacknowledgedHigh': 2,
                'unacknowledgedCritical': 1,
            },
        )
        expected_security_activity = [
            {
                'date': (timezone.localdate() - timedelta(days=offset)).isoformat(),
                'high': 2 if offset == 0 else 0,
                'critical': 2 if offset == 0 else 0,
            }
            for offset in range(6, -1, -1)
        ]
        self.assertEqual(
            response.data['insights'],
            {
                'securityActivity': expected_security_activity,
                'agentVersions': [
                    {'version': '1.0.4', 'total': 1, 'online': 0, 'offline': 1},
                    {'version': '1.1.0', 'total': 1, 'online': 1, 'offline': 0},
                    {'version': 'unknown', 'total': 1, 'online': 0, 'offline': 1},
                ],
                'deviceTypes': {'localAgent': 1, 'pos': 1, 'tv': 1, 'control': 1},
            },
        )
        self.assertEqual(
            sum(response.data['insights']['deviceTypes'].values()),
            response.data['summary']['activeDevices'],
        )

        branches = {branch['restaurantName']: branch for branch in response.data['branches']}
        self.assertEqual(list(branches), ['Alpha branch', 'Beta branch', 'Delta branch', 'Gamma branch'])
        self.assertEqual(
            branches['Alpha branch']['devices'],
            {
                'active': 3,
                'online': 3,
                'revoked': 1,
                'activeLocalAgent': 1,
                'activePOS': 1,
                'activeTV': 1,
                'activeControl': 0,
                'telegramSubscriptions': 2,
                'lastSeenAt': alpha_pos.last_seen_at.isoformat(),
            },
        )
        self.assertEqual(branches['Beta branch']['devices']['activeLocalAgent'], 0)
        self.assertEqual(branches['Beta branch']['devices']['telegramSubscriptions'], 1)
        self.assertEqual(branches['Gamma branch']['devices']['activeLocalAgent'], 0)
        self.assertEqual(branches['Gamma branch']['devices']['telegramSubscriptions'], 0)
        telegram_subscription_queries = [
            query['sql']
            for query in captured_queries.captured_queries
            if 'telegram_reports_telegrambranchsubscription' in query['sql'].lower()
        ]
        self.assertEqual(len(telegram_subscription_queries), 1)
        self.assertEqual(branches['Alpha branch']['security']['unacknowledgedHigh'], 1)
        self.assertEqual(branches['Alpha branch']['security']['unacknowledgedCritical'], 0)
        self.assertIsNotNone(branches['Alpha branch']['security']['lastEventAt'])
        self.assertEqual(branches['Alpha branch']['agent']['id'], str(alpha_agent.id))
        self.assertEqual(branches['Alpha branch']['agent']['version'], '1.1.0')
        self.assertEqual(branches['Alpha branch']['agent']['protocolVersion'], 3)
        self.assertEqual(branches['Alpha branch']['agent']['deviceStatus'], Device.Status.ACTIVE)
        self.assertTrue(branches['Alpha branch']['agent']['online'])
        self.assertFalse(branches['Beta branch']['agent']['online'])
        self.assertFalse(branches['Delta branch']['agent']['online'])
        self.assertFalse(branches['Delta branch']['agent']['isActive'])
        self.assertIsNone(branches['Gamma branch']['agent'])

    def test_security_activity_uses_current_timezone_calendar_days_and_includes_acknowledged_events(self):
        report_timezone = ZoneInfo('Asia/Tashkent')
        report_now = datetime(2026, 1, 7, 20, 30, tzinfo=datetime_timezone.utc)

        event_timestamps = (
            (SecurityEvent.Severity.HIGH, datetime(2026, 1, 1, 18, 59, tzinfo=datetime_timezone.utc)),
            (SecurityEvent.Severity.HIGH, datetime(2026, 1, 1, 19, 0, tzinfo=datetime_timezone.utc)),
            (SecurityEvent.Severity.CRITICAL, datetime(2026, 1, 6, 18, 59, tzinfo=datetime_timezone.utc)),
            (SecurityEvent.Severity.HIGH, datetime(2026, 1, 7, 20, 29, tzinfo=datetime_timezone.utc)),
            (SecurityEvent.Severity.CRITICAL, datetime(2026, 1, 8, 19, 0, tzinfo=datetime_timezone.utc)),
        )
        for index, (severity, created_at) in enumerate(event_timestamps):
            event = SecurityEvent.objects.create(
                event_type=f'TIMEZONE_BOUNDARY_{index}',
                severity=severity,
                acknowledged_at=report_now if index == 2 else None,
                acknowledged_by=self.superuser if index == 2 else None,
            )
            SecurityEvent.objects.filter(pk=event.pk).update(created_at=created_at)

        SecurityEvent.objects.create(
            event_type='IGNORED_INFO',
            severity=SecurityEvent.Severity.INFO,
        )

        self.client.force_authenticate(self.superuser)
        with timezone.override(report_timezone), patch(
            'apps.devices.monitoring_views.timezone.now',
            return_value=report_now,
        ):
            response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            response.data['insights']['securityActivity'],
            [
                {'date': '2026-01-02', 'high': 1, 'critical': 0},
                {'date': '2026-01-03', 'high': 0, 'critical': 0},
                {'date': '2026-01-04', 'high': 0, 'critical': 0},
                {'date': '2026-01-05', 'high': 0, 'critical': 0},
                {'date': '2026-01-06', 'high': 0, 'critical': 1},
                {'date': '2026-01-07', 'high': 0, 'critical': 0},
                {'date': '2026-01-08', 'high': 1, 'critical': 0},
            ],
        )

    def test_device_online_count_uses_a_five_minute_last_seen_window(self):
        now = timezone.now()
        restaurant = Restaurant.objects.create(name='Five minute device branch')
        self.create_device(
            restaurant=restaurant,
            index=201,
            device_type=Device.Type.POS_TERMINAL,
            last_seen_at=now - timedelta(minutes=4, seconds=59),
        )
        self.create_device(
            restaurant=restaurant,
            index=202,
            device_type=Device.Type.TV_MONITOR,
            last_seen_at=now - timedelta(minutes=5, seconds=1),
        )

        self.client.force_authenticate(self.superuser)
        with patch('apps.devices.monitoring_views.timezone.now', return_value=now):
            response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        branch = response.data['branches'][0]
        self.assertEqual(branch['devices']['active'], 2)
        self.assertEqual(branch['devices']['online'], 1)

    def test_business_partner_filter_scopes_the_complete_monitoring_snapshot(self):
        now = timezone.now()
        selected_partner = BusinessPartner.objects.create(
            inn='monitoring-partner-1',
            company_name='Selected partner',
        )
        other_partner = BusinessPartner.objects.create(
            inn='monitoring-partner-2',
            company_name='Other partner',
        )
        selected_branch = Restaurant.objects.create(
            name='Selected branch',
            business_partner=selected_partner,
        )
        other_branch = Restaurant.objects.create(
            name='Other branch',
            business_partner=other_partner,
        )
        self.create_device(
            restaurant=selected_branch,
            index=301,
            device_type=Device.Type.POS_TERMINAL,
            last_seen_at=now,
        )
        self.create_device(
            restaurant=other_branch,
            index=302,
            device_type=Device.Type.TV_MONITOR,
            last_seen_at=now,
        )
        SecurityEvent.objects.create(
            event_type='SELECTED_HIGH',
            severity=SecurityEvent.Severity.HIGH,
            restaurant=selected_branch,
        )
        SecurityEvent.objects.create(
            event_type='OTHER_CRITICAL',
            severity=SecurityEvent.Severity.CRITICAL,
            restaurant=other_branch,
        )
        SecurityEvent.objects.create(
            event_type='PLATFORM_HIGH',
            severity=SecurityEvent.Severity.HIGH,
        )

        self.client.force_authenticate(self.superuser)
        response = self.client.get(
            self.endpoint,
            {'business_partner_id': str(selected_partner.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            response.data['summary'],
            {
                'totalBranches': 1,
                'agentOnline': 0,
                'agentOffline': 0,
                'agentMissing': 1,
                'activeDevices': 1,
                'revokedDevices': 0,
                'activePOSTerminals': 1,
                'pendingPairings': 0,
                'unacknowledgedHigh': 1,
                'unacknowledgedCritical': 0,
            },
        )
        self.assertEqual(
            response.data['insights']['deviceTypes'],
            {'localAgent': 0, 'pos': 1, 'tv': 0, 'control': 0},
        )
        self.assertEqual(
            response.data['insights']['securityActivity'][-1],
            {'date': timezone.localdate().isoformat(), 'high': 1, 'critical': 0},
        )
        self.assertEqual(
            [branch['restaurantName'] for branch in response.data['branches']],
            ['Selected branch'],
        )

    def test_security_event_list_can_be_scoped_by_business_partner(self):
        selected_partner = BusinessPartner.objects.create(
            inn='security-partner-1',
            company_name='Selected security partner',
        )
        other_partner = BusinessPartner.objects.create(
            inn='security-partner-2',
            company_name='Other security partner',
        )
        selected_branch = Restaurant.objects.create(
            name='Selected security branch',
            business_partner=selected_partner,
        )
        other_branch = Restaurant.objects.create(
            name='Other security branch',
            business_partner=other_partner,
        )
        selected_event = SecurityEvent.objects.create(
            event_type='SELECTED_PARTNER_EVENT',
            severity=SecurityEvent.Severity.HIGH,
            restaurant=selected_branch,
        )
        SecurityEvent.objects.create(
            event_type='OTHER_PARTNER_EVENT',
            severity=SecurityEvent.Severity.CRITICAL,
            restaurant=other_branch,
        )
        SecurityEvent.objects.create(
            event_type='PLATFORM_EVENT',
            severity=SecurityEvent.Severity.HIGH,
        )

        self.client.force_authenticate(self.superuser)
        response = self.client.get(
            '/api/v1/admin/security-events/',
            {'business_partner_id': str(selected_partner.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['total'], 1)
        self.assertEqual(response.data['data'][0]['id'], str(selected_event.id))

    def test_endpoint_allows_superuser_and_product_owner_but_denies_other_accounts(self):
        for user in (self.superuser, self.product_owner):
            with self.subTest(username=user.username):
                self.client.force_authenticate(user)
                response = self.client.get(self.endpoint)
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.client.force_authenticate(self.regular_user)
        denied = self.client.get(self.endpoint)
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=None)
        unauthenticated = self.client.get(self.endpoint)
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(
        DJANGO_PRODUCTION=True,
        DEVICE_LEGACY_POS_MIGRATION_ENABLED=True,
        DEVICE_LEGACY_MIGRATION_STARTED_AT='2026-08-01T00:00:00Z',
        DEVICE_LEGACY_MIGRATION_DEADLINE='2026-09-01T00:00:00Z',
    )
    def test_get_is_read_only_and_does_not_change_migration_or_pos_session_state(self):
        now = timezone.now()
        restaurant = Restaurant.objects.create(name='Read-only branch')
        employee = User.objects.create_user(
            username='read-only-employee',
            password='unused',
            restaurant=restaurant,
        )
        session = AuthSession.objects.create(
            user=employee,
            restaurant=restaurant,
            token_key_hash='9' * 64,
            surface=AuthSession.Surface.POS,
            status=AuthSession.Status.ACTIVE,
            expires_at=now + timedelta(hours=1),
        )
        agent, _ = LocalAgent.issue_for_restaurant(restaurant=restaurant, name='Read-only agent')
        pos = self.create_device(
            restaurant=restaurant,
            index=99,
            device_type=Device.Type.POS_TERMINAL,
            last_seen_at=now,
        )

        original_session_updated_at = session.updated_at
        original_agent_updated_at = agent.updated_at
        original_device_updated_at = pos.updated_at
        migration_window_before = legacy_pos_migration_enabled(now=now)

        self.client.force_authenticate(self.superuser)
        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        mutating_queries = [
            query['sql']
            for query in captured_queries.captured_queries
            if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        ]
        self.assertEqual(mutating_queries, [])
        session.refresh_from_db()
        agent.refresh_from_db()
        pos.refresh_from_db()
        self.assertEqual(session.status, AuthSession.Status.ACTIVE)
        self.assertIsNone(session.device_id)
        self.assertEqual(session.updated_at, original_session_updated_at)
        self.assertEqual(agent.updated_at, original_agent_updated_at)
        self.assertEqual(pos.status, Device.Status.ACTIVE)
        self.assertEqual(pos.updated_at, original_device_updated_at)
        self.assertEqual(legacy_pos_migration_enabled(now=now), migration_window_before)
