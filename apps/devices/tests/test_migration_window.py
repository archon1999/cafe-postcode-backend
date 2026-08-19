from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import core.settings as project_settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.devices.migration_window import (
    legacy_local_agent_auth_enabled,
    legacy_cohort_eligible,
    legacy_pos_migration_enabled,
    legacy_tv_migration_enabled,
    legacy_unbound_pos_session_auth_enabled,
    pos_device_proof_required,
)
from apps.local_agents.models import LocalAgent
from apps.kitchen.models import TvMonitorDevice
from apps.kitchen.models.tv_monitor import hash_tv_monitor_secret
from apps.restaurants.models import Restaurant
from apps.users.models import AuthSession, User


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


class DeviceMigrationWindowTests(TestCase):
    def test_production_validator_never_allows_pos_proof_to_be_disabled(self):
        with (
            patch.object(project_settings, 'PRODUCTION_MODE', True),
            patch.object(project_settings, 'DEVICE_POS_PROOF_REQUIRED_VALUE', False),
            self.assertRaisesMessage(ImproperlyConfigured, 'must remain enabled in production'),
        ):
            project_settings.validate_production_environment()

    @override_settings(
        DJANGO_PRODUCTION=True,
        DEVICE_POS_PROOF_REQUIRED=False,
        DEVICE_LEGACY_POS_MIGRATION_ENABLED=True,
        DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED=True,
        DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=True,
        DEVICE_LEGACY_TV_MIGRATION_ENABLED=True,
    )
    def test_future_deadline_temporarily_opens_only_configured_paths(self):
        now = timezone.now()
        with override_settings(
            DEVICE_LEGACY_MIGRATION_STARTED_AT=iso(now - timedelta(minutes=1)),
            DEVICE_LEGACY_MIGRATION_DEADLINE=iso(now + timedelta(hours=1)),
        ):
            self.assertTrue(legacy_pos_migration_enabled())
            self.assertTrue(legacy_local_agent_auth_enabled())
            self.assertTrue(legacy_unbound_pos_session_auth_enabled())
            self.assertTrue(legacy_tv_migration_enabled())
            self.assertFalse(pos_device_proof_required())

    @override_settings(
        DJANGO_PRODUCTION=True,
        DEVICE_POS_PROOF_REQUIRED=False,
        DEVICE_LEGACY_POS_MIGRATION_ENABLED=True,
        DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED=True,
        DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=True,
        DEVICE_LEGACY_TV_MIGRATION_ENABLED=True,
    )
    def test_expired_or_missing_deadline_closes_legacy_and_requires_pos_proof(self):
        for deadline in ('', iso(timezone.now() - timedelta(seconds=1))):
            with self.subTest(deadline=deadline), override_settings(DEVICE_LEGACY_MIGRATION_DEADLINE=deadline):
                self.assertFalse(legacy_pos_migration_enabled())
                self.assertFalse(legacy_local_agent_auth_enabled())
                self.assertFalse(legacy_unbound_pos_session_auth_enabled())
                self.assertFalse(legacy_tv_migration_enabled())
                self.assertTrue(pos_device_proof_required())

    @override_settings(DJANGO_PRODUCTION=True)
    def test_only_records_created_on_or_before_cutover_are_in_the_legacy_cohort(self):
        started_at = timezone.now()
        with override_settings(DEVICE_LEGACY_MIGRATION_STARTED_AT=iso(started_at)):
            self.assertTrue(legacy_cohort_eligible(created_at=started_at - timedelta(seconds=1)))
            self.assertTrue(legacy_cohort_eligible(created_at=started_at))
            self.assertFalse(legacy_cohort_eligible(created_at=started_at + timedelta(microseconds=1)))


class FinalizeDeviceMigrationCommandTests(TestCase):
    def test_dry_run_is_safe_and_apply_revokes_only_unbound_pos_sessions(self):
        restaurant = Restaurant.objects.create(name='Migration branch')
        user = User.objects.create_user(username='migration-user', password='unused', restaurant=restaurant)
        now = timezone.now()
        unbound = AuthSession.objects.create(
            user=user,
            restaurant=restaurant,
            token_key_hash='1' * 64,
            surface=AuthSession.Surface.POS,
            expires_at=now + timedelta(hours=1),
        )
        dashboard = AuthSession.objects.create(
            user=user,
            restaurant=restaurant,
            token_key_hash='2' * 64,
            surface=AuthSession.Surface.DASHBOARD,
            expires_at=now + timedelta(hours=1),
        )
        LocalAgent.issue_for_restaurant(restaurant=restaurant, name='Unmigrated Agent')
        TvMonitorDevice.objects.create(
            restaurant=restaurant,
            token_hash=hash_tv_monitor_secret('legacy-tv'),
            paired_at=now,
        )

        output = StringIO()
        call_command('finalize_device_migration', stdout=output)
        unbound.refresh_from_db()
        self.assertEqual(unbound.status, AuthSession.Status.ACTIVE)
        self.assertIn(
            'DRY-RUN: unbound_active_pos_sessions=1 unmigrated_active_local_agents=1 '
            'unmigrated_active_tv_monitors=1',
            output.getvalue(),
        )

        output = StringIO()
        call_command('finalize_device_migration', '--apply', stdout=output)
        unbound.refresh_from_db()
        dashboard.refresh_from_db()
        self.assertEqual(unbound.status, AuthSession.Status.REVOKED)
        self.assertEqual(dashboard.status, AuthSession.Status.ACTIVE)
        self.assertIn('APPLIED: unbound_active_pos_sessions=1', output.getvalue())
