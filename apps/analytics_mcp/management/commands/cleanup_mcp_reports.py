from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.analytics_mcp.models import ReportSnapshot


class Command(BaseCommand):
    help = "Delete expired analytics snapshots in bounded batches; schedule hourly."

    def handle(self, *args, **options):
        count = 0
        while ids := list(
            ReportSnapshot.objects.filter(expires_at__lte=timezone.now()).values_list(
                "pk", flat=True
            )[:500]
        ):
            removed, _ = ReportSnapshot.objects.filter(pk__in=ids).delete()
            count += removed
        self.stdout.write(f"Removed {count} expired snapshots.")
