from django.db import transaction
from apps.telegram_reports.client import TelegramAPIError
from .models import ManagementBotUpdate


def process_update(pk):
    from .bot import ManagementBotHandler
    retry = False
    with transaction.atomic():
        update = ManagementBotUpdate.objects.select_for_update().get(pk=pk)
        if update.status in ('done', 'rejected'):
            return
        update.attempts += 1
        try:
            with transaction.atomic():
                # Failed delivery rolls back mutations; retry uses the same nonce.
                ManagementBotHandler().handle(update.payload)
            update.status = 'done'
        except Exception as error:
            update.error_code = type(error).__name__[:80]
            permanent = isinstance(error, TelegramAPIError) and error.error_code in (400, 401, 403)
            retry = not permanent and update.attempts < 3
            update.status = 'pending' if retry else 'rejected'
        if update.status in ('done', 'rejected'):
            update.payload = {}
        update.save(update_fields=['status', 'payload', 'attempts', 'error_code', 'updated_at'])
    if retry:
        raise RuntimeError('Management bot delivery failed; queued retry required.') from None
