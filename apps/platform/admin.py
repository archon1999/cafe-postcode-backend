from django.contrib import admin

from .models import BusinessPartner, RestaurantEntitlement, Tariff

admin.site.register(BusinessPartner)
admin.site.register(Tariff)
admin.site.register(RestaurantEntitlement)
