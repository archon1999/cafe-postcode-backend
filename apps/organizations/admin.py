from django.contrib import admin

from .models import CashDesk, Device, DistributionPoint, FeatureConfig, PrepStation, Restaurant

admin.site.register(Restaurant)
admin.site.register(FeatureConfig)
admin.site.register(Device)
admin.site.register(PrepStation)
admin.site.register(CashDesk)
admin.site.register(DistributionPoint)
