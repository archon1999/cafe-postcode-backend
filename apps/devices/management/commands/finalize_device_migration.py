from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.local_agents.models import LocalAgent
from apps.kitchen.models import TvMonitorDevice
from apps.users.models import AuthSession


class Command(BaseCommand):
    help = 'Audit or revoke legacy unbound POS sessions at the final device cutover.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Revoke active POS sessions that are not bound to an approved device.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        unbound_sessions = AuthSession.objects.select_for_update().filter(
            surface=AuthSession.Surface.POS,
            status=AuthSession.Status.ACTIVE,
            device__isnull=True,
        )
        session_count = unbound_sessions.count()
        unmigrated_agents = LocalAgent.objects.filter(is_active=True, device__isnull=True).count()
        unmigrated_tvs = TvMonitorDevice.objects.filter(revoked_at__isnull=True, device__isnull=True).count()

        if options['apply'] and session_count:
            unbound_sessions.update(
                status=AuthSession.Status.REVOKED,
                revoked_at=now,
                updated_at=now,
            )

        mode = 'APPLIED' if options['apply'] else 'DRY-RUN'
        self.stdout.write(
            f'{mode}: unbound_active_pos_sessions={session_count} '
            f'unmigrated_active_local_agents={unmigrated_agents} '
            f'unmigrated_active_tv_monitors={unmigrated_tvs}'
        )
        if not options['apply']:
            self.stdout.write('Run again with --apply only after the migration summary is acceptable.')
