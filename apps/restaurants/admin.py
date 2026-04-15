from django.contrib import admin

from .models import CashDesk, DistributionPoint, PrepStation, Restaurant

admin.site.register(Restaurant)
admin.site.register(PrepStation)
admin.site.register(CashDesk)
admin.site.register(DistributionPoint)
