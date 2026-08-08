from django.contrib import admin

from .models import KitchenAnnouncement, KitchenTicket

admin.site.register(KitchenTicket)
admin.site.register(KitchenAnnouncement)
