from django.contrib import admin

from .models import CashShift, Payment, PaymentRefund, Receipt

admin.site.register(CashShift)
admin.site.register(Payment)
admin.site.register(PaymentRefund)
admin.site.register(Receipt)
