from django.contrib import admin

from apps.telegram_reports.models import (
    TelegramAccount,
    TelegramBranchSubscription,
    TelegramProcessedUpdate,
    TelegramReportDelivery,
)


admin.site.register(TelegramAccount)
admin.site.register(TelegramBranchSubscription)
admin.site.register(TelegramProcessedUpdate)
admin.site.register(TelegramReportDelivery)

