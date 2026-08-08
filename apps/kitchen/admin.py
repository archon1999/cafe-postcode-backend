from django.contrib import admin

from .models import KitchenAnnouncement, KitchenTicket, KitchenTicketLine

admin.site.register(KitchenTicket)
admin.site.register(KitchenTicketLine)
admin.site.register(KitchenAnnouncement)
