from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone


REPORT_SCHEDULES = (
    ("telegram_reports.daily", "apps.telegram_reports.tasks.dispatch_daily_reports", "5 0 * * *"),
    ("telegram_reports.weekly", "apps.telegram_reports.tasks.dispatch_weekly_reports", "10 0 * * 1"),
    ("telegram_reports.monthly", "apps.telegram_reports.tasks.dispatch_monthly_reports", "15 0 1 * *"),
)


def ensure_report_schedules() -> bool:
    from croniter import croniter
    from django_q.models import Schedule

    try:
        local_now = timezone.localtime()
        for name, func, cron in REPORT_SCHEDULES:
            next_run = croniter(cron, local_now).get_next(type(local_now))
            schedule, created = Schedule.objects.get_or_create(
                name=name,
                defaults={
                    "func": func,
                    "schedule_type": Schedule.CRON,
                    "cron": cron,
                    "repeats": -1,
                    "next_run": next_run,
                },
            )
            if not created:
                changed = False
                for field, value in (
                    ("func", func),
                    ("schedule_type", Schedule.CRON),
                    ("cron", cron),
                    ("repeats", -1),
                ):
                    if getattr(schedule, field) != value:
                        setattr(schedule, field, value)
                        changed = True
                if changed:
                    schedule.next_run = next_run
                    schedule.save(
                        update_fields=("func", "schedule_type", "cron", "repeats", "next_run")
                    )
    except (ProgrammingError, OperationalError):
        return False
    return True

